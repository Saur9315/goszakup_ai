from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

import pandas as pd
import streamlit as st

from client import Api, ApiError

st.set_page_config(page_title="GosZakup AI", page_icon="📊", layout="wide")

EXAMPLES = [
    "Найди закупки с отклонением цены > 30% от средневзвешенной по ЕНСТРУ за 2025 год",
    "Оцени адекватность цены лота №85092773-ОК3 относительно аналогичных контрактов "
    "других ведомств",
    "Выяви нетипичное завышение количества ТРУ по сравнению с предыдущими годами "
    "у Дирекции государственных резиденций",
    "2025 жылы Ұлттық госпитальдің сатып алу тиімділігі қандай?",
]
VERDICTS = {
    "fair": "в пределах рынка",
    "elevated": "выше рынка",
    "overpriced": "завышена",
    "underpriced": "аномально низкая",
    "insufficient_data": "недостаточно данных",
}
LEVELS = {"locality": "город", "region": "регион", "national": "вся РК"}
YEARS = [2024, 2025, 2026]
LINK = st.column_config.LinkColumn("Ссылка", display_text="открыть")

state = st.session_state
for key, default in (("token", None), ("username", None), ("thread_id", None), ("messages", [])):
    state.setdefault(key, default)


def api() -> Api:
    return Api(state.token)


def logout() -> None:
    state.token = state.username = state.thread_id = None
    state.messages = []


def show_error(e: ApiError) -> None:
    if e.status == 401 and state.token:
        logout()
        st.warning("Сессия истекла, войдите снова.")
    else:
        st.error(e.detail)


def money(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f} ₸".replace(",", " ")


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1%}".replace(".", ",")


@st.cache_data(ttl=60, show_spinner=False)
def health() -> dict[str, Any]:
    return dict(Api().get("/api/health"))


@st.cache_data(ttl=3600, show_spinner=False)
def organizations() -> dict[str, str]:
    return {o["name_ru"]: o["bin"] for o in Api().get("/api/orgs")}


def open_thread(thread_id: str) -> None:
    try:
        answers = api().get(f"/api/threads/{thread_id}/answers")
    except ApiError as e:
        show_error(e)
        return
    state.thread_id = thread_id
    state.messages = [
        message
        for a in answers
        for message in (
            {"role": "user", "content": a["question"]},
            {"role": "assistant", "content": a["markdown"]},
        )
    ]


def sidebar(auth: bool) -> None:
    with st.sidebar:
        st.title("GosZakup AI")
        st.caption("Анализ госзакупок РК по данным OWS v3")
        if auth and not state.token:
            with st.form("login"):
                username = st.text_input("Логин")
                password = st.text_input("Пароль", type="password")
                if st.form_submit_button("Войти", width="stretch"):
                    try:
                        r = Api().post(
                            "/api/auth/login", {"username": username, "password": password}
                        )
                    except ApiError as e:
                        st.error("Неверный логин или пароль" if e.status == 401 else e.detail)
                    else:
                        state.token, state.username = r["token"], r["username"]
                        st.rerun()
            return
        if state.username:
            left, right = st.columns([3, 2])
            left.write(f"**{state.username}**")
            if right.button("Выйти", width="stretch"):
                logout()
                st.rerun()
        if st.button("Новый диалог", icon="➕", width="stretch"):
            state.thread_id, state.messages = None, []
            st.rerun()
        if not state.token:
            st.caption("Без входа диалог хранится только в этой вкладке браузера.")
            return
        st.subheader("Мои диалоги")
        try:
            threads = api().get("/api/threads")
        except ApiError as e:
            show_error(e)
            return
        if not threads:
            st.caption("Пока нет диалогов")
        for t in threads[:30]:
            current = t["thread_id"] == state.thread_id
            if st.button(
                t["title"],
                key=f"thread-{t['thread_id']}",
                type="primary" if current else "secondary",
                width="stretch",
            ):
                open_thread(t["thread_id"])
                st.rerun()


def ask(question: str) -> None:
    state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        status = st.status("Агент работает…", expanded=True)
        answer: dict[str, Any] | None = None
        try:
            for event, data in api().stream(question, state.thread_id):
                if event == "stage":
                    status.write(f"✓ {data['label']}")
                elif event == "answer":
                    answer = data["answer"]
                elif event == "error":
                    raise ApiError(500, data["detail"])
        except ApiError as e:
            status.update(label="Ошибка", state="error")
            show_error(e)
            return
        if answer is None:
            status.update(label="Ответ не получен", state="error")
            return
        status.update(
            label=f"Готово за {answer['latency_ms'] / 1000:.1f} с", state="complete", expanded=False
        )
        v = answer["verification"]
        caption = (
            f"{answer['model']} · проверка цифр: {v['numbers_grounded']} из {v['numbers_total']}"
            f" · run {answer['run_id']}"
        )
        st.markdown(answer["markdown"])
        st.caption(caption)
    state.thread_id = answer["thread_id"]
    state.messages.append({"role": "assistant", "content": answer["markdown"], "caption": caption})


def chat_tab() -> None:
    for m in state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("caption"):
                st.caption(m["caption"])
    if not state.messages:
        st.caption("Задайте вопрос на русском или казахском языке. Примеры:")
        for q in EXAMPLES:
            if st.button(q, key=f"example-{q}"):
                state.pending = q
                st.rerun()
    question = st.chat_input("Вопрос о закупках") or state.pop("pending", None)
    if question:
        ask(question)
        st.rerun()


def fair_price_tab() -> None:
    with st.form("fair-price"):
        lot = st.text_input("Номер лота", placeholder="85092773-ОК3")
        if st.form_submit_button("Оценить"):
            try:
                state.fair_price = api().get(f"/api/fair-price/{quote(lot.strip())}")
            except ApiError as e:
                show_error(e)
    for r in state.get("fair_price", []):
        t = r["target"]
        st.subheader(f"{t['item_name']} — лот {t['lot_number']}")
        st.caption(
            f"{t['customer_name']} · {t.get('locality_name') or t.get('region_name') or '—'}"
            f" · ЕНС ТРУ {t['enstru_code']}"
        )
        cols = st.columns(5)
        cols[0].metric(f"Цена за {t.get('unit_name') or 'ед.'}", money(t["price"]))
        cols[1].metric(
            "Fair Price", money(r["fair_price"]), delta=pct(r["deviation"]), delta_color="inverse"
        )
        cols[2].metric("Коридор P25–P75", f"{money(r['p25'])} – {money(r['p75'])}")
        cols[3].metric("Вердикт", VERDICTS[r["verdict"]])
        cols[4].metric("Уверенность", f"{r['confidence']:.2f} ({r['confidence_label']})")
        group = (
            f"подкласс «{t['subclass_label']}» (похожие описания)"
            if r["peer_group"] == "subclass"
            else "все позиции кода ЕНС ТРУ"
        )
        st.write(
            f"Аналоги: N = {r['n']} от {r['n_customers']} заказчиков · "
            f"уровень: {LEVELS.get(r['level'] or '', '—')} · группа: {group}"
        )
        for note in r["limitations"]:
            st.caption(f"⚠ {note}")
        if r["comparables"]:
            df = pd.DataFrame(r["comparables"])
            df["link"] = df["contract_url"].fillna(df["announce_url"])
            st.dataframe(
                df[
                    [
                        "sign_date",
                        "customer_name",
                        "similarity",
                        "region_name",
                        "price",
                        "adjusted_price",
                        "quantity",
                        "link",
                    ]
                ],
                column_config={
                    "sign_date": "Дата",
                    "customer_name": "Заказчик-аналог",
                    "similarity": st.column_config.NumberColumn("Сходство описания", format="%.2f"),
                    "region_name": "Регион",
                    "price": st.column_config.NumberColumn("Цена, ₸", format="%.0f"),
                    "adjusted_price": st.column_config.NumberColumn(
                        "С поправками, ₸", format="%.0f"
                    ),
                    "quantity": "Кол-во",
                    "link": LINK,
                },
                hide_index=True,
                width="stretch",
            )
        with st.expander("Метод"):
            st.write(r["method"])


def org_filter(key: str) -> list[str]:
    names = organizations()
    return [names[n] for n in st.multiselect("Организации", list(names), key=key)]


def price_anomalies() -> None:
    with st.form("price-anomalies"):
        cols = st.columns([3, 2, 1, 1])
        with cols[0]:
            bins = org_filter("pa-orgs")
        years = cols[1].multiselect("Годы", YEARS, default=[2025])
        threshold = cols[2].number_input("Порог, %", min_value=5, max_value=500, value=30, step=5)
        confirmed = cols[3].checkbox("Только подтверждённые", value=True)
        if st.form_submit_button("Показать"):
            try:
                state.price_report = api().get(
                    "/api/anomalies/price",
                    threshold=threshold / 100,
                    bins=bins,
                    years=years,
                    confirmed_only=str(confirmed).lower(),
                    limit=200,
                )
            except ApiError as e:
                show_error(e)
    report = state.get("price_report")
    if not report:
        return
    cols = st.columns(4)
    cols[0].metric("Проверено позиций", f"{report['checked']:,}".replace(",", " "))
    cols[1].metric("Выше порога (критерий ТЗ)", f"{report['matched']:,}".replace(",", " "))
    cols[2].metric("Подтверждено (|z| > 2)", f"{report['confirmed']:,}".replace(",", " "))
    cols[3].metric("Оценка переплаты", money(report["confirmed_overpayment_kzt"]))
    if not report["items"]:
        st.info("Ничего не найдено")
        return
    df = pd.DataFrame(report["items"])
    df["deviation"] = df["deviation"] * 100
    df["group"] = df["subclass_label"].map(lambda s: f"подкласс «{s}»" if s else "весь код")
    view = df[
        [
            "lot_number",
            "customer_name",
            "item_name",
            "price",
            "peer_wavg_price",
            "deviation",
            "robust_z",
            "peer_n",
            "group",
            "overpayment_kzt",
            "contract_url",
        ]
    ]
    st.dataframe(
        view,
        column_config={
            "lot_number": "Лот",
            "customer_name": "Заказчик",
            "item_name": "Предмет",
            "price": st.column_config.NumberColumn("Цена, ₸", format="%.0f"),
            "peer_wavg_price": st.column_config.NumberColumn("Средневзв. аналогов", format="%.0f"),
            "deviation": st.column_config.NumberColumn("Отклонение, %", format="%.0f"),
            "robust_z": st.column_config.NumberColumn("z", format="%.1f"),
            "peer_n": "N аналогов",
            "group": "Группа сравнения",
            "overpayment_kzt": st.column_config.NumberColumn("Переплата, ₸", format="%.0f"),
            "contract_url": LINK,
        },
        hide_index=True,
        width="stretch",
    )
    st.download_button(
        "Скачать CSV", view.to_csv(index=False).encode("utf-8-sig"), "price_anomalies.csv"
    )
    with st.expander("Метод"):
        st.write(report["method"])


def volume_anomalies() -> None:
    with st.form("volume-anomalies"):
        cols = st.columns([3, 2, 1, 1])
        with cols[0]:
            bins = org_filter("va-orgs")
        years = cols[1].multiselect("Годы", YEARS[1:], default=YEARS[1:])
        min_ratio = cols[2].number_input("Рост не менее, ×", min_value=1.1, value=1.5, step=0.1)
        confirmed = cols[3].checkbox("Только подтверждённые моделью", value=False)
        if st.form_submit_button("Показать"):
            try:
                state.volume_report = api().get(
                    "/api/anomalies/volume",
                    min_ratio=min_ratio,
                    bins=bins,
                    years=years,
                    confirmed_only=str(confirmed).lower(),
                    limit=200,
                )
            except ApiError as e:
                show_error(e)
    report = state.get("volume_report")
    if not report:
        return
    cols = st.columns(3)
    cols[0].metric("Проверено пар", f"{report['checked']:,}".replace(",", " "))
    cols[1].metric("Рост выше порога", f"{report['matched']:,}".replace(",", " "))
    cols[2].metric("Подтверждено Isolation Forest", f"{report['confirmed']:,}".replace(",", " "))
    if not report["items"]:
        st.info("Ничего не найдено")
        return
    df = pd.DataFrame(report["items"])
    view = df[
        [
            "customer_name",
            "enstru_name",
            "year",
            "quantity",
            "unit_name",
            "baseline_quantity",
            "ratio",
            "peer_ratio",
            "extra_amount",
            "confirmed",
            "isolation_score",
        ]
    ]
    st.dataframe(
        view,
        column_config={
            "customer_name": "Заказчик",
            "enstru_name": "ТРУ",
            "year": st.column_config.NumberColumn("Год", format="%d"),
            "quantity": "Количество",
            "unit_name": "Единица",
            "baseline_quantity": "Среднее за прошлые годы",
            "ratio": st.column_config.NumberColumn("Рост, ×", format="%.2f"),
            "peer_ratio": st.column_config.NumberColumn("Рост у других, ×", format="%.2f"),
            "extra_amount": st.column_config.NumberColumn("Сумма прироста, ₸", format="%.0f"),
            "confirmed": "Нетипично по модели",
            "isolation_score": st.column_config.NumberColumn("Оценка модели", format="%.3f"),
        },
        hide_index=True,
        width="stretch",
    )
    st.download_button(
        "Скачать CSV", view.to_csv(index=False).encode("utf-8-sig"), "volume_anomalies.csv"
    )
    with st.expander("Метод"):
        st.write(report["method"])


def efficiency_tab() -> None:
    years = st.multiselect("Годы", YEARS, default=[2025], key="eff-years")
    try:
        rows = api().get("/api/efficiency", years=years)
    except ApiError as e:
        show_error(e)
        return
    if not rows:
        st.info("Нет данных")
        return
    df = pd.DataFrame(rows)
    for col in ("economy_share", "single_source_share", "lots_failed_share"):
        df[col] = df[col].astype(float) * 100
    st.dataframe(
        df[
            [
                "name_ru",
                "year",
                "contract_amount",
                "contracts",
                "suppliers",
                "economy_share",
                "single_source_share",
                "lots_failed_share",
                "avg_days_publish_to_sign",
            ]
        ],
        column_config={
            "name_ru": "Организация",
            "year": st.column_config.NumberColumn("Год", format="%d"),
            "contract_amount": st.column_config.NumberColumn("Сумма договоров, ₸", format="%.0f"),
            "contracts": "Договоров",
            "suppliers": "Поставщиков",
            "economy_share": st.column_config.NumberColumn("Экономия, %", format="%.1f"),
            "single_source_share": st.column_config.NumberColumn(
                "Из одного источника, %", format="%.1f"
            ),
            "lots_failed_share": st.column_config.NumberColumn(
                "Несостоявшиеся лоты, %", format="%.1f"
            ),
            "avg_days_publish_to_sign": st.column_config.NumberColumn(
                "Дней от объявления до договора", format="%.0f"
            ),
        },
        hide_index=True,
        width="stretch",
    )
    st.caption("Доля закупок из одного источника, %")
    chart = df.groupby("name_ru")["single_source_share"].mean().sort_values()
    st.bar_chart(chart, horizontal=True, height=max(300, 22 * len(chart)))


def data_tab() -> None:
    try:
        s = api().get("/api/status")
    except ApiError as e:
        show_error(e)
        return
    as_of = s["data_as_of"]
    st.metric(
        "Данные на",
        datetime.fromisoformat(as_of).strftime("%d.%m.%Y %H:%M UTC") if as_of else "—",
    )
    for run in s["sync_running"]:
        st.info(f"Идёт загрузка «{run['command']}» с {run['started_at'][:16].replace('T', ' ')}")
    df = pd.DataFrame(s["checks"])
    if df.empty:
        return
    df["share"] = df["failed_count"] / df["total_count"].where(df["total_count"] > 0) * 100
    st.subheader("Проверки качества данных")
    st.dataframe(
        df[["check_name", "severity", "failed_count", "total_count", "share", "checked_at"]],
        column_config={
            "check_name": "Проверка",
            "severity": "Уровень",
            "failed_count": "Нарушений",
            "total_count": "Проверено",
            "share": st.column_config.NumberColumn("Доля, %", format="%.1f"),
            "checked_at": "Когда",
        },
        hide_index=True,
        width="stretch",
    )


try:
    auth = bool(health().get("auth"))
except ApiError as e:
    st.error(e.detail)
    st.stop()

sidebar(auth)
if auth and not state.token:
    st.info("Войдите, чтобы задавать вопросы агенту и видеть свои диалоги.")
    st.stop()

chat, fair, anomalies, efficiency, data = st.tabs(
    ["Чат", "Fair Price", "Аномалии", "Эффективность", "Данные"]
)
with chat:
    chat_tab()
with fair:
    fair_price_tab()
with anomalies:
    prices, volumes = st.tabs(["Цены", "Объёмы"])
    with prices:
        price_anomalies()
    with volumes:
        volume_anomalies()
with efficiency:
    efficiency_tab()
with data:
    data_tab()
