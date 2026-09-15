#!/usr/bin/env python3
"""Timeweb Cloud CLI для курса AI Prime.

Всё, что нужно для публикации приложения: баланс, тарифы, серверы,
домены, DNS. Любая трата денег требует подтверждения.

Ключ берётся из .env (TIMEWEB_CLOUD_TOKEN) и никогда не печатается.

Примеры:
    python3 twc.py balance
    python3 twc.py presets
    python3 twc.py server-create --name myapp --ram 4096
    python3 twc.py servers
    python3 twc.py domain-check example.ru
    python3 twc.py domain-register example.ru
    python3 twc.py dns-set example.ru 1.2.3.4
    python3 twc.py subdomain-add example.ru dev
    python3 twc.py server-delete 123456
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.timeweb.cloud/api/v1"


# ─────────────────────────── вывод ───────────────────────────


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"ОШИБКА: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def confirm(question: str) -> bool:
    """Подтверждение траты денег. Молча не тратим никогда."""
    log("")
    log("=" * 60)
    log(question)
    log("=" * 60)
    answer = input("Введите «да» для подтверждения: ").strip().lower()
    return answer in ("да", "yes", "y")


# ─────────────────────────── доступ ───────────────────────────


def find_env() -> Path | None:
    """Ищем .env рядом со скриптом и выше по дереву."""
    here = Path(__file__).resolve()
    for folder in [Path.cwd(), *here.parents]:
        candidate = folder / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_token() -> str:
    token = os.getenv("TIMEWEB_CLOUD_TOKEN")
    if token:
        return token

    env_file = find_env()
    if env_file:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "TIMEWEB_CLOUD_TOKEN":
                return value.strip().strip("\"'")

    die(
        "не найден TIMEWEB_CLOUD_TOKEN.\n"
        "Скопируйте .env.example в .env и впишите свой ключ.\n"
        "Ключ берётся в панели Timeweb → API и терминал."
    )
    return ""


def call(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {load_token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:500]
        if e.code == 401:
            die("ключ Timeweb не принят. Проверьте TIMEWEB_CLOUD_TOKEN в .env")
        if e.code == 423:
            die("нужно подтверждение по SMS — код придёт на телефон владельца аккаунта")
        if "no_paid" in detail or "vds_blocked" in detail:
            die("не хватает денег на балансе. Пополните в панели Timeweb — по API это невозможно")
        die(f"Timeweb ответил {e.code}: {detail}")
    except urllib.error.URLError as e:
        die(f"нет связи с Timeweb: {e.reason}")
    return {}


def find_tld(zone: str) -> dict | None:
    """Ищем доменную зону в справочнике Timeweb (355 зон, отдаются страницами)."""
    offset = 0
    while offset < 600:
        page = call(f"/tlds?limit=100&offset={offset}").get("top_level_domains", [])
        if not page:
            return None
        for t in page:
            if t.get("name") == zone:
                return t
        offset += 100
    return None


# ─────────────────────────── команды ───────────────────────────


def cmd_balance(args) -> None:
    data = call("/account/finances").get("finances", {})
    balance = data.get("balance", 0)
    log(f"Баланс: {balance} ₽")
    hourly = data.get("hourly_cost")
    if hourly:
        log(f"Тратится: {hourly} ₽/час (~{round(hourly * 24 * 30)} ₽/мес)")
    if balance < 1500:
        log("")
        log("⚠️  Мало денег. Для сервера и домена нужно примерно 1 500 ₽.")
        log("   Пополнить можно только руками в панели Timeweb.")


def cmd_presets(args) -> None:
    presets = call("/presets/servers").get("server_presets", [])
    rows = [p for p in presets if p.get("location", "").startswith("ru")]
    rows.sort(key=lambda p: p.get("price", 0))

    log(f"{'ID':>7}  {'CPU':>3}  {'RAM':>7}  {'Диск':>7}  {'Цена/мес':>9}")
    log("-" * 45)
    for p in rows[:20]:
        ram = f"{p.get('ram', 0) // 1024} ГБ"
        disk = f"{p.get('disk', 0) // 1024} ГБ"
        log(f"{p.get('id'):>7}  {p.get('cpu'):>3}  {ram:>7}  {disk:>7}  {p.get('price'):>7} ₽")

    log("")
    log("Сколько брать: 2 ГБ — статика и боты, 4 ГБ — обычное приложение,")
    log("8 ГБ — видео, распознавание речи, модели.")


def cmd_servers(args) -> None:
    servers = call("/servers").get("servers", [])
    if not servers:
        log("Серверов нет.")
        return
    for s in servers:
        ips = [n.get("ip") for n in s.get("networks", []) for n in n.get("ips", [])] or ["—"]
        log(f"[{s.get('id')}] {s.get('name')} · {s.get('status')} · {', '.join(str(i) for i in ips)}")


def cmd_server_create(args) -> None:
    presets = call("/presets/servers").get("server_presets", [])
    candidates = [
        p for p in presets
        if p.get("location", "").startswith("ru") and p.get("ram", 0) >= args.ram
    ]
    if not candidates:
        die(f"нет тарифа с памятью от {args.ram} МБ")
    preset = min(candidates, key=lambda p: p.get("price", 0))

    images = call("/os/servers").get("servers_os", [])
    ubuntu = [i for i in images if i.get("name", "").lower() == "ubuntu"]
    ubuntu.sort(key=lambda i: i.get("version", ""), reverse=True)
    if not ubuntu:
        die("не нашёл образ Ubuntu")
    os_id = ubuntu[0]["id"]

    price = preset.get("price")
    if not confirm(
        f"Аренда сервера «{args.name}»\n"
        f"  {preset.get('cpu')} CPU · {preset.get('ram') // 1024} ГБ памяти · "
        f"{preset.get('disk') // 1024} ГБ диска\n"
        f"  Цена: {price} ₽ в месяц\n\n"
        f"Списание начнётся сразу."
    ):
        log("Отменено, ничего не создано.")
        return

    result = call("/servers", "POST", {
        "name": args.name,
        "preset_id": preset["id"],
        "os_id": os_id,
        "is_ddos_guard": False,
    })
    server = result.get("server", {})
    sid = server.get("id")
    log(f"Сервер создаётся, id {sid}. Ждём запуска…")

    for _ in range(60):
        time.sleep(5)
        s = call(f"/servers/{sid}").get("server", {})
        if s.get("status") == "on":
            ips = [ip.get("ip") for n in s.get("networks", []) for ip in n.get("ips", [])]
            log(f"Готово. IP: {', '.join(str(i) for i in ips)}")
            return
    log("Сервер создан, но ещё запускается. Проверьте: python3 twc.py servers")


def cmd_server_delete(args) -> None:
    s = call(f"/servers/{args.server_id}").get("server", {})
    if not confirm(
        f"УДАЛЕНИЕ сервера «{s.get('name')}» (id {args.server_id})\n\n"
        f"Все данные на диске будут потеряны безвозвратно.\n"
        f"Это действие нельзя отменить."
    ):
        log("Отменено, сервер на месте.")
        return
    call(f"/servers/{args.server_id}", "DELETE")
    log("Сервер удалён.")


def cmd_domain_check(args) -> None:
    result = call(f"/check-domain/{args.fqdn}")
    available = result.get("is_domain_available")
    if available:
        zone = args.fqdn.rsplit(".", 1)[-1]
        tld = find_tld(zone)
        log(f"Домен {args.fqdn} свободен.")
        if tld:
            log(f"Цена регистрации: {tld.get('price')} ₽ за первый год.")
            log(f"Продление: {tld.get('prolong_price')} ₽ в год.")
    else:
        log(f"Домен {args.fqdn} занят. Попробуйте другое имя или зону.")


def cmd_domain_register(args) -> None:
    check = call(f"/check-domain/{args.fqdn}")
    if not check.get("is_domain_available"):
        die(f"домен {args.fqdn} занят")

    zone = args.fqdn.rsplit(".", 1)[-1]
    tld = find_tld(zone) or {}
    reg = tld.get("price", "?")
    renew = tld.get("prolong_price", "?")

    persons = call("/persons").get("persons", [])
    confirmed = [p for p in persons if p.get("is_person_confirmed")]
    if not confirmed:
        die(
            "нет подтверждённых данных владельца.\n"
            "Домен регистрируется на конкретного человека — добавьте данные "
            "в панели Timeweb → Домены → Персоны."
        )
    person_id = confirmed[0]["id"]

    warning = ""
    if zone in ("ru", "рф", "su"):
        warning = "\n⚠️  Для зоны .ru данные владельца публичны — это правило реестра.\n"

    if not confirm(
        f"Регистрация домена {args.fqdn}\n"
        f"  Цена: {reg} ₽ за первый год\n"
        f"  Продление: {renew} ₽ в год\n"
        f"{warning}\n"
        f"Покупка необратима, деньги не возвращаются."
    ):
        log("Отменено, домен не куплен.")
        return

    request = call("/domains-requests", "POST", {
        "action": "register",
        "fqdn": args.fqdn,
        "person_id": person_id,
        "period": 1,
    })
    rid = request.get("domain_request", {}).get("id")
    log(f"Заявка создана (id {rid}). Оплачиваем с баланса…")

    call(f"/domains-requests/{rid}", "PATCH", {"money_source": "use"})
    log(f"Домен {args.fqdn} оплачен и регистрируется.")
    log("Регистрация занимает до нескольких часов — это нормально.")


def cmd_dns_set(args) -> None:
    call(f"/domains/{args.fqdn}/dns-records", "POST", {
        "type": "A",
        "value": args.ip,
        "subdomain": None,
    })
    log(f"Домен {args.fqdn} направлен на {args.ip}.")
    log("")
    log("⚠️  Адрес расходится по интернету от получаса до нескольких часов.")
    log("   Пока ждёте — проверяйте сайт по IP.")


def cmd_subdomain_add(args) -> None:
    call(f"/domains/{args.fqdn}/subdomains/{args.name}", "POST")
    log(f"Поддомен {args.name}.{args.fqdn} создан.")


def cmd_domains(args) -> None:
    domains = call("/domains").get("domains", [])
    if not domains:
        log("Доменов нет.")
        return
    for d in domains:
        log(f"{d.get('fqdn')} · до {d.get('expiration')}")


# ─────────────────────────── разбор аргументов ───────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Timeweb Cloud для курса AI Prime",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("balance", help="сколько денег на счету")
    sub.add_parser("presets", help="какие есть тарифы серверов")
    sub.add_parser("servers", help="мои серверы")
    sub.add_parser("domains", help="мои домены")

    p = sub.add_parser("server-create", help="арендовать сервер")
    p.add_argument("--name", required=True, help="имя сервера")
    p.add_argument("--ram", type=int, default=4096, help="память в МБ (по умолчанию 4096)")

    p = sub.add_parser("server-delete", help="удалить сервер")
    p.add_argument("server_id", help="id сервера")

    p = sub.add_parser("domain-check", help="свободен ли домен")
    p.add_argument("fqdn", help="например example.ru")

    p = sub.add_parser("domain-register", help="купить домен")
    p.add_argument("fqdn", help="например example.ru")

    p = sub.add_parser("dns-set", help="направить домен на сервер")
    p.add_argument("fqdn")
    p.add_argument("ip")

    p = sub.add_parser("subdomain-add", help="создать поддомен")
    p.add_argument("fqdn")
    p.add_argument("name", help="например dev")

    args = parser.parse_args()
    handler = globals()["cmd_" + args.command.replace("-", "_")]
    handler(args)


if __name__ == "__main__":
    main()
