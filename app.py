import importlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from pandas.api.types import is_datetime64tz_dtype

import pandas as pd
import requests
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
HEYREACH_DIR = REPO_ROOT / "heyreach-data-filtraition"
FORMD_DIR = REPO_ROOT / "form_d"
LENS_DIR = REPO_ROOT / "lens"
FULL_WORK_DIR = Path(__file__).resolve().parent

# Ensure local full-work-view directory is searched first so local copies of modules are used
for path in [FULL_WORK_DIR, REPO_ROOT, HEYREACH_DIR, FORMD_DIR, LENS_DIR]:
    if path.exists():
        sys.path.insert(0, str(path))


def safe_import(module_name: str):
    try:
        return importlib.import_module(module_name)
    except SystemExit:
        return None
    except Exception:
        return None

location_normalizer_mod = safe_import("location_normalizer")
form_d_companies_mod = safe_import("form_d_companies")
form_d_enricher_mod = safe_import("form_d_enricher")
patent_pipeline_mod = safe_import("patent_pipeline")
list_and_campaign_mod = safe_import("list_and_campaign_creation")


def _get_streamlit_secret(key: str, default: Any = None) -> Any:
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def _parse_accounts_secret(value: Any) -> List[dict]:
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if isinstance(value, list):
        parsed = []
        for acc in value:
            if not isinstance(acc, dict) or "id" not in acc:
                continue
            try:
                parsed.append({"id": int(acc["id"]), "name": str(acc.get("name", "")).strip()})
            except (ValueError, TypeError):
                continue
        return parsed
    return []


def _load_heyreach_config() -> tuple[Optional[str], List[dict]]:
    api_key: Optional[str] = None
    accounts: List[dict] = []

    if list_and_campaign_mod is not None:
        api_key = getattr(list_and_campaign_mod, "API_KEY", None)
        accounts = getattr(list_and_campaign_mod, "LINKEDIN_ACCOUNTS", []) or []
        if not accounts:
            load_fn = getattr(list_and_campaign_mod, "load_linkedin_accounts", None)
            if callable(load_fn):
                try:
                    accounts = load_fn() or []
                except Exception:
                    accounts = []
        if not api_key:
            load_key_fn = getattr(list_and_campaign_mod, "load_api_key", None)
            if callable(load_key_fn):
                try:
                    api_key = load_key_fn()
                except Exception:
                    api_key = None

    if not api_key:
        api_key = os.getenv("HEYREACH_API_KEY") or os.getenv("OPENAI_API_KEY") or _get_streamlit_secret("HEYREACH_API_KEY")
        if api_key and isinstance(api_key, str):
            api_key = api_key.strip() or None

    if not accounts:
        accounts = _parse_accounts_secret(_get_streamlit_secret("linkedin_accounts") or _get_streamlit_secret("LINKEDIN_ACCOUNTS"))

    return api_key, accounts


heyreach_api_key, heyreach_accounts = _load_heyreach_config()
run_pipeline_custom = getattr(list_and_campaign_mod, "run_pipeline_custom", None) if list_and_campaign_mod is not None else None
load_linkedin_accounts = getattr(list_and_campaign_mod, "load_linkedin_accounts", None) if list_and_campaign_mod is not None else None

# Build readable account labels for UI (used in extraction and pipeline sender selection)
account_labels = [f"{acc.get('name','')} ({acc.get('id')})" for acc in heyreach_accounts]

REGION_MAP: Dict[str, List[str]] = {
    "🇪🇺 EU (All 27)": [
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
        "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
        "PL", "PT", "RO", "SK", "SI", "ES", "SE"
    ],
    "🇬🇧 UK & Ireland": ["GB", "IE"],
    "🌍 Middle East": ["AE", "SA", "QA", "BH", "KW", "OM", "IL", "EG", "JO", "LB"],
    "🇺🇸 US": ["US"],
    "🌏 AU & Rich Asia": ["AU", "NZ", "SG", "HK", "JP", "KR", "TW", "MY"],
    "🏔️ DACH": ["DE", "AT", "CH"],
    "🌲 Nordics": ["SE", "NO", "DK", "FI", "IS"],
    "🇵🇱 Poland": ["PL"],
}

POSITION_CATEGORIES: Dict[str, List[str]] = {
    "👑 Executive/C-Suite": ["ceo", "cto", "cfo", "coo", "chief", "director", "executive", "president", "vp", "vice president"],
    "⚙️ Engineering/Tech": ["engineer", "developer", "architect", "programmer", "coder", "software", "tech", "it"],
    "🎯 Leadership": ["lead", "head", "manager", "senior", "principal", "staff"],
    "📊 Analyst/Research": ["analyst", "researcher", "scientist", "data", "business analyst"],
    "🚀 Founder/Co-founder": ["founder", "co-founder", "entrepreneur"],
    "📈 Sales/Marketing": ["sales", "marketing", "product", "growth", "business development"],
}


def load_openai_client():
    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI or python-dotenv package is missing.") from exc

    load_dotenv()
    api_key = __import__("os").environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment or .env file.")

    return OpenAI(api_key=api_key)


def run_async(coro):
    try:
        loop = __import__("asyncio").get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(__import__("asyncio").run, coro)
            return future.result()
    except RuntimeError:
        return __import__("asyncio").run(coro)


def format_messages(messages: List[dict]) -> str:
    if not messages:
        return ""
    parts = []
    for msg in messages:
        sender = "ME" if msg.get("sender") == "ME" else "THEM"
        body = (msg.get("body") or msg.get("text") or "").strip().replace("\n", " ")
        ts = msg.get("createdAt", "")
        if ts and "T" in ts:
            ts = ts.split("T")[0]
        parts.append(f"[{ts}] {sender}: {body}" if ts else f"{sender}: {body}")
    return " | ".join(parts)


def conversations_to_dataframe(conversations: List[dict], sender_account: dict) -> pd.DataFrame:
    rows = []
    for conv in conversations:
        profile = conv.get("correspondentProfile") or {}
        row = {
            "sender_id": sender_account.get("id", ""),
            "sender_name": sender_account.get("name", ""),
            "lead_linkedin_url": profile.get("profileUrl", ""),
            "lead_linkedin_id": profile.get("linkedin_id", ""),
            "lead_first_name": profile.get("firstName", ""),
            "lead_last_name": profile.get("lastName", ""),
            "lead_position": profile.get("position", ""),
            "lead_location": profile.get("location", ""),
            "lead_company": profile.get("companyName", ""),
            "lead_headline": profile.get("headline", ""),
            "lead_email": profile.get("emailAddress", ""),
            "conversation_id": conv.get("id", ""),
            "last_message_at": conv.get("lastMessageAt", ""),
            "last_message_text": (conv.get("lastMessageText") or "").replace("\n", " "),
            "last_message_sender": "ME" if conv.get("lastMessageSender") == "ME" else "THEM",
            "total_messages": conv.get("totalMessages", 0),
            "messages_text": format_messages(conv.get("messages", [])),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def fetch_conversations_for_account_sync(
    account_id: int,
    account_name: str,
    progress_bar: Optional[st.delta_generator] = None,
    status_text: Optional[st.delta_generator] = None,
) -> List[dict]:
    api_key = heyreach_api_key
    if not api_key:
        raise RuntimeError("HeyReach API key is not loaded.")

    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    all_conversations: List[dict] = []
    seen_conv_ids = set()
    offset = 0
    page = 0

    if status_text:
        status_text.text(f"Извлечение данных для аккаунта: {account_name}")

    while page < 500:
        time.sleep(60 / 300)
        payload = {
            "filters": {
                "linkedInAccountIds": [account_id],
                "campaignIds": [],
                "searchString": "",
                "leadLinkedInId": "",
                "leadProfileUrl": "",
                "tags": [],
                "seen": None,
            },
            "offset": offset,
            "limit": 100,
        }

        try:
            response = requests.post(
                f"https://api.heyreach.io/api/public/inbox/GetConversationsV2",
                headers=headers,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            items = data.get("items", [])
            if not items:
                break
            for item in items:
                conv_id = item.get("id")
                if conv_id and conv_id not in seen_conv_ids:
                    seen_conv_ids.add(conv_id)
                    all_conversations.append(item)
            if len(items) < 100:
                break
            offset += 100
            page += 1
            if progress_bar and page % 5 == 0:
                progress_bar.progress(min(page / 50, 1.0))
        except Exception as exc:
            if status_text:
                status_text.error(f"Ошибка при извлечении данных для {account_name}: {exc}")
            break

    return all_conversations


def load_csv_dataframe(uploaded_file: Any) -> Optional[pd.DataFrame]:
    try:
        if hasattr(uploaded_file, "read"):
            return pd.read_csv(uploaded_file, low_memory=False)
        return pd.read_csv(uploaded_file, low_memory=False)
    except Exception as exc:
        st.error(f"Невозможно загрузить CSV: {exc}")
        return None


def normalize_heyreach_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.str.strip()
    if "country_code" in df.columns:
        df["country_code"] = df["country_code"].astype(str).str.strip().str.upper()
    if "last_message_at" in df.columns:
        df["last_message_at"] = pd.to_datetime(df["last_message_at"], errors="coerce")
    return df


def filter_heyreach_dataframe(
    df: pd.DataFrame,
    selected_countries: List[str],
    date_range: Optional[List[datetime]],
    selected_position_categories: List[str],
    explicit_position_filter: str,
    include_missing_location: bool,
) -> pd.DataFrame:
    filtered = df.copy()
    if selected_countries and "country_code" in filtered.columns:
        filtered = filtered[filtered["country_code"].isin(selected_countries)]

    # Date range: handle timezone-aware datetimes by aligning start/end types with the series
    if date_range and len(date_range) == 2 and "last_message_at" in filtered.columns:
        start, end = date_range
        if pd.notna(start) and pd.notna(end):
            ser = filtered["last_message_at"]
            # normalize start/end to timestamps
            start_ts = pd.to_datetime(start)
            end_ts = pd.to_datetime(end)

            # If series is timezone-aware, make start/end timezone-aware too
            try:
                if is_datetime64tz_dtype(ser.dtype):
                    tz = ser.dt.tz
                    if start_ts.tzinfo is None:
                        start_ts = start_ts.tz_localize(tz)
                    else:
                        start_ts = start_ts.tz_convert(tz)
                    if end_ts.tzinfo is None:
                        end_ts = end_ts.tz_localize(tz)
                    else:
                        end_ts = end_ts.tz_convert(tz)
                # perform between on the original series
                filtered = filtered[ser.between(start_ts, end_ts)]
            except Exception:
                # Fallback: compare on naive timestamps by removing tz info from series
                try:
                    ser_naive = ser.dt.tz_convert(None)
                except Exception:
                    ser_naive = ser.dt.tz_localize(None)
                filtered = filtered[ser_naive.between(pd.to_datetime(start).replace(tzinfo=None), pd.to_datetime(end).replace(tzinfo=None))]

    if explicit_position_filter and "lead_position" in filtered.columns:
        mask = filtered["lead_position"].astype(str).str.contains(explicit_position_filter, case=False, na=False)
        filtered = filtered[mask]
    if selected_position_categories and "lead_position" in filtered.columns:
        category_keywords = [kw for cat in selected_position_categories for kw in POSITION_CATEGORIES.get(cat, [])]
        if category_keywords:
            pattern = "|".join([re.escape(k) for k in category_keywords])
            filtered = filtered[filtered["lead_position"].astype(str).str.contains(pattern, case=False, na=False)]
    if not include_missing_location and "lead_location" in filtered.columns:
        filtered = filtered[filtered["lead_location"].astype(str).str.strip() != ""]
    return filtered


def get_available_countries(df: pd.DataFrame) -> List[str]:
    if "country_code" not in df.columns:
        return []
    return sorted([c for c in df["country_code"].dropna().unique() if len(str(c)) == 2])


def run_heyreach_pipeline(filtered_df: pd.DataFrame, account_ids: List[int], campaign_name: str, list_name: str, msg1: str, msg1_fb: str, msg2: str, msg2_fb: str, msg3: str, msg3_fb: str, timezone: str, start_time: str, end_time: str, exclude_contacted: bool, exclude_other_acc: bool, exclude_sender: bool) -> Dict:
    if run_pipeline_custom is None:
        raise RuntimeError("HeyReach pipeline function is not available.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        filtered_df.to_csv(tmp.name, index=False, encoding="utf-8-sig")
        tmp_path = tmp.name

    try:
        return run_pipeline_custom(
            tmp_path,
            campaign_name,
            list_name,
            msg1,
            msg1_fb,
            msg2,
            msg2_fb,
            msg3,
            msg3_fb,
            timezone,
            start_time,
            end_time,
            exclude_contacted,
            exclude_other_acc,
            exclude_sender,
            account_ids=account_ids,
        )
    finally:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass


def load_attached_csv(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return None


def render_heyreach_tab():
    st.header("HeyReach Lead Filter & Export")
    st.markdown(
        "Загрузите CSV из HeyReach или извлеките данные с API, затем примените фильтры и скачайте результат."
    )

    data_source = st.radio(
        "Источник данных",
        ["📥 Загрузить CSV файл", "🌐 Извлечь из HeyReach API"],
        key="heyreach_data_source",
    )

    df: Optional[pd.DataFrame] = None
    if data_source == "🌐 Извлечь из HeyReach API":
        if not heyreach_api_key:
            st.warning(
                "HeyReach API integration недоступна. Установите HEYREACH_API_KEY в переменных окружения или Streamlit secrets."
            )
            data_source = "📥 Загрузить CSV файл"
        else:
            account_labels = [f"{acc.get('name','')} ({acc.get('id')})" for acc in heyreach_accounts]
            if not account_labels:
                st.info(
                    "Аккаунты HeyReach не найдены. Добавьте список аккаунтов в Streamlit secrets под ключом `linkedin_accounts`."
                )
            selected = st.multiselect(
                "Выберите аккаунты HeyReach для извлечения данных",
                options=account_labels,
                default=account_labels[:1] if account_labels else [],
            )
            if st.button("📥 Извлечь данные лидов"):
                if not selected:
                    st.error("Выберите хотя бы один аккаунт.")
                else:
                    with st.spinner("Извлечение conversations из HeyReach..."):
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        rows = []
                        for label in selected:
                            account = next((acc for acc, lbl in zip(heyreach_accounts, account_labels) if lbl == label), None)
                            if not account:
                                continue
                            conversations = fetch_conversations_for_account_sync(
                                account_id=account["id"],
                                account_name=account.get("name", str(account["id"])),
                                progress_bar=progress_bar,
                                status_text=status_text,
                            )
                            if conversations:
                                rows.append(conversations_to_dataframe(conversations, account))
                        if rows:
                            df = pd.concat(rows, ignore_index=True)
                            st.success(f"Извлечено {len(df)} записей.")
                            st.session_state["heyreach_df"] = df
                        else:
                            st.warning("Не удалось извлечь данные. Проверьте настройки API.")

    if data_source == "📥 Загрузить CSV файл":
        uploaded = st.file_uploader("Загрузите CSV-файл HeyReach", type=["csv"], key="heyreach_csv")
        if uploaded is not None:
            df = load_csv_dataframe(uploaded)
            if df is not None:
                st.session_state["heyreach_df"] = df
        elif "heyreach_df" in st.session_state:
            df = st.session_state["heyreach_df"]
        else:
            st.info("Загрузите CSV-файл для начала работы.")
            return

    if df is None:
        st.warning("Нет данных для отображения.")
        return

    df = normalize_heyreach_df(df)
    # If a location normalizer module exists, apply it to enrich location/country fields
    try:
        if location_normalizer_mod is not None:
            normalize_fn = getattr(location_normalizer_mod, "normalize_locations_df", None) or getattr(location_normalizer_mod, "normalize_locations", None)
            if normalize_fn is not None:
                df = normalize_fn(df)
    except Exception:
        # silently continue if location normalization fails
        pass
    st.markdown("### 📄 Исходные данные")
    st.write(f"Строк: {len(df):,}")
    st.dataframe(df.head(10), use_container_width=True)

    with st.expander("🔍 Фильтры", expanded=True):
        country_codes = get_available_countries(df)
        selected_regions = [name for name in REGION_MAP if st.checkbox(name, value=False, key=f"region_{name}")]
        selected_countries: List[str] = []
        for region in selected_regions:
            selected_countries.extend(REGION_MAP.get(region, []))

        if not selected_countries:
            selected_countries = st.multiselect(
                "Выберите страны (2-символьные коды)",
                options=country_codes,
                default=[],
                key="heyreach_countries",
            )

        valid_dates = df["last_message_at"].dropna() if "last_message_at" in df.columns else pd.Series([], dtype="datetime64[ns]")
        date_range = None
        if not valid_dates.empty:
            min_date = valid_dates.min().date()
            max_date = valid_dates.max().date()
            date_range = st.date_input("Диапазон даты последнего сообщения", [min_date, max_date], key="heyreach_date_range")
        else:
            st.info("Колонка last_message_at не найдена или не распознаётся как дата.")

        position_search = st.text_input("Поиск по позиции или заголовку", key="heyreach_position_search")
        selected_categories = [name for name in POSITION_CATEGORIES if st.checkbox(name, value=False, key=f"pos_cat_{name}")]
        include_missing_location = st.checkbox("Включить лидов без location", value=True, key="heyreach_include_missing_location")

    filtered_df = filter_heyreach_dataframe(
        df,
        selected_countries,
        list(date_range) if date_range and len(date_range) == 2 else None,
        selected_categories,
        position_search,
        include_missing_location,
    )

    st.markdown("### 📊 Результаты фильтрации")
    col1, col2 = st.columns(2)
    col1.metric("Всего записей", f"{len(df):,}")
    col2.metric("Отфильтровано", f"{len(filtered_df):,}")

    available_display = [c for c in [
        "sender_name", "lead_linkedin_url", "lead_first_name", "lead_last_name",
        "last_message_text", "country_code", "lead_position", "lead_location",
        "last_message_at"
    ] if c in filtered_df.columns]
    if available_display:
        st.dataframe(filtered_df[available_display], use_container_width=True)
    else:
        st.dataframe(filtered_df, use_container_width=True)

    if not filtered_df.empty:
        csv_buffer = filtered_df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            label="⬇️ Скачать отфильтрованные данные",
            data=csv_buffer,
            file_name=f"filtered_heysreach_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )

    if run_pipeline_custom is not None:
        with st.expander("🚀 Запустить HeyReach Pipeline", expanded=False):
            st.markdown("Этот запуск работает только с конфигурацией HeyReach в папке `heyreach-data-filtraition`.")
            campaign_name = st.text_input("Название кампании", value=f"Full Work View Campaign {datetime.now().strftime('%Y%m%d_%H%M')}")
            list_name = st.text_input("Название списка", value=f"Full Work View List {datetime.now().strftime('%Y%m%d_%H%M')}")
            msg1 = st.text_area("Сообщение 1", value="Hi {FIRST_NAME}, I came across your profile and would love to connect!")
            msg1_fb = st.text_area("Fallback Message 1", value="Hi there, I came across your profile and would love to connect!")
            msg2 = st.text_area("Сообщение 2", value="Hi {FIRST_NAME}, thanks for connecting! Would love to explore how we might work together.")
            msg2_fb = st.text_area("Fallback Message 2", value="Hi there, thanks for connecting! Would love to explore how we might work together.")
            msg3 = st.text_area("Сообщение 3", value="Hi {FIRST_NAME}, just following up in case my last message got buried!")
            msg3_fb = st.text_area("Fallback Message 3", value="Hi there, just following up in case my last message got buried!")
            schedule_timezone = st.text_input("Timezone", value="Europe/Amsterdam")
            schedule_start = st.text_input("Start time", value="09:00:00")
            schedule_end = st.text_input("End time", value="18:00:00")
            exclude_contacted = st.checkbox("Exclude contacted from other campaigns", value=True)
            exclude_other_acc = st.checkbox("Exclude leads contacted by other accounts", value=False)
            exclude_sender = st.checkbox("Exclude leads contacted by sender in other campaigns", value=False)

            if st.button("🚀 Запустить HeyReach Pipeline"):
                if filtered_df.empty:
                    st.error("Сначала отфильтруйте данные, чтобы запустить пайплайн.")
                else:
                    try:
                        account_ids = [acc["id"] for acc in heyreach_accounts] if heyreach_accounts else None
                        result = run_heyreach_pipeline(
                            filtered_df,
                            account_ids=account_ids,
                            campaign_name=campaign_name,
                            list_name=list_name,
                            msg1=msg1,
                            msg1_fb=msg1_fb,
                            msg2=msg2,
                            msg2_fb=msg2_fb,
                            msg3=msg3,
                            msg3_fb=msg3_fb,
                            timezone=schedule_timezone,
                            start_time=schedule_start,
                            end_time=schedule_end,
                            exclude_contacted=exclude_contacted,
                            exclude_other_acc=exclude_other_acc,
                            exclude_sender=exclude_sender,
                        )
                        st.success("HeyReach pipeline выполнен.")
                        st.json(result)
                    except Exception as exc:
                        st.error(f"Ошибка запуска пайплайна: {exc}")


def render_form_d_tab():
    st.header("SEC EDGAR Parser")
    if form_d_companies_mod is None:
        st.warning("SEC EDGAR модуль недоступен. Проверьте папку `form_d` и зависимости.")
        return

    st.markdown("Парсер Form D/C/A с фильтрацией по индустриям и ключевым словам.")

    forms = st.multiselect(
        "Формы",
        options=list(form_d_companies_mod.SUPPORTED_FORMS.keys()),
        default=["D"],
        format_func=lambda x: f"{x} ({form_d_companies_mod.SUPPORTED_FORMS[x]})",
    )
    days = st.number_input("Дней назад", min_value=1, max_value=365, value=30)
    selected_industries = st.multiselect(
        "Индустрии (Form D)",
        options=form_d_companies_mod.TARGET_INDUSTRIES_D,
        default=form_d_companies_mod.TARGET_INDUSTRIES_D[:5],
    )
    selected_keywords_cat = st.multiselect(
        "Категории ключевых слов",
        options=list(form_d_companies_mod.INDUSTRY_KEYWORDS.keys()),
        default=[],
    )
    st.markdown("---")
    min_amount_d = st.number_input("Мин. сумма Form D ($)", value=500_000, step=100_000)
    min_amount_ca = st.number_input("Мин. сумма Form C/A ($)", value=100_000, step=50_000)
    max_amount = st.number_input("Макс. сумма ($)", value=20_000_000, step=1_000_000)
    custom_keywords = st.text_area("Свои ключевые слова (через запятую)", placeholder="fintech, payments, healthtech")

    kw_list: List[str] = []
    for cat in selected_keywords_cat:
        kw_list.extend(form_d_companies_mod.INDUSTRY_KEYWORDS[cat])
    if custom_keywords:
        kw_list.extend([k.strip() for k in custom_keywords.split(",") if k.strip()])
    kw_q = form_d_companies_mod.build_query(kw_list) if kw_list else None

    start_d = (datetime.today() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_d = datetime.today().strftime('%Y-%m-%d')

    if st.button("🚀 Запустить парсинг"):
        if not forms:
            st.error("Выберите хотя бы одну форму.")
        else:
            with st.spinner("Парсим SEC EDGAR..."):
                try:
                    ind_d = selected_industries if "D" in forms else None
                    results = form_d_companies_mod.fetch_all(
                        forms, start_d, end_d, kw_q,
                        min_amount_d, min_amount_ca, max_amount,
                        ind_d, kw_list, keep_all=False, show_reasons=False, verbose=False,
                    )
                except Exception as exc:
                    st.error(f"Ошибка: {exc}")
                    results = []

            if results:
                df = pd.DataFrame(results)
                st.session_state["form_d_df"] = df
                st.success(f"Найдено {len(results)} компаний.")
            else:
                st.warning("Ничего не найдено.")

    if "form_d_df" in st.session_state:
        df = st.session_state["form_d_df"]
        st.markdown("### Результаты парсинга")
        st.dataframe(df.head(20), use_container_width=True)
        st.download_button(
            label="⬇️ Скачать результаты парсинга",
            data=df.to_csv(index=False, encoding="utf-8-sig"),
            file_name=f"sec_parser_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )

        if st.button("🔍 Find Contacts"):
            if form_d_enricher_mod is None:
                st.error("Модуль обогащения не найден. Установите OpenAI и python-dotenv.")
            else:
                try:
                    client = load_openai_client()
                except Exception as exc:
                    st.error(str(exc))
                    return

                with st.spinner("Обогащаем контакты..."):
                    df_copy = df.copy()
                    progress_bar = st.progress(0)
                    for idx, row in df_copy.iterrows():
                        company_name = str(row.get("company_name") or "").strip()
                        cik = str(row.get("cik") or "").strip() or None
                        if company_name:
                            enriched = form_d_enricher_mod.enrich_row(client, company_name, cik, verbose=False)
                            df_copy.at[idx, "linkedin"] = enriched.get("linkedin")
                            df_copy.at[idx, "email"] = enriched.get("email")
                            df_copy.at[idx, "website"] = enriched.get("website")
                        progress_bar.progress((idx + 1) / len(df_copy))
                    st.session_state["form_d_df"] = df_copy
                    st.success("Обогащение завершено.")
                    st.dataframe(df_copy.head(20), use_container_width=True)
                    st.download_button(
                        label="⬇️ Скачать обогащенные данные",
                        data=df_copy.to_csv(index=False, encoding="utf-8-sig"),
                        file_name=f"sec_parser_enriched_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                    )

    sample_path = FULL_WORK_DIR / "sec_results_enr_contacts_found (1).csv"
    if sample_path.exists():
        if st.button("📑 Показать прикреплённый пример sec_results_enr_contacts_found"):
            sample_df = load_attached_csv(sample_path)
            if sample_df is not None:
                st.dataframe(sample_df, use_container_width=True)


def render_patent_tab():
    st.header("Patent Results Viewer")
    sample_path = FULL_WORK_DIR / "patent_results(2)(1).csv"
    uploaded = st.file_uploader("Upload Patent CSV to view", type=["csv"], key="patent_csv_view")

    df = None
    if uploaded is not None:
        df = load_csv_dataframe(uploaded)
    elif sample_path.exists():
        if st.button("📑 Показать прикреплённый пример patent_results"):
            df = load_attached_csv(sample_path)

    if df is None:
        st.info("Загрузите CSV или нажмите кнопку для просмотра примера.")
        return

    st.write(f"Rows: {len(df):,}")
    st.dataframe(df, use_container_width=True)
    csv = df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button("⬇️ Скачать patent CSV", data=csv, file_name=f"patent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv")


def render_layoffs_tab():
    st.header("Layoffs — Browse & Filter")
    sample_path = FULL_WORK_DIR / "layoffs.csv"
    if not sample_path.exists():
        st.warning("layoffs.csv not found in project folder.")
        return

    df = load_attached_csv(sample_path)
    if df is None:
        st.error("Не удалось загрузить layoffs.csv")
        return

    st.markdown("Simple filtering controls for the layoffs dataset.")
    st.write(f"Rows: {len(df):,}")

    # Find common filter columns
    industry_col = next((c for c in df.columns if "industry" in c.lower()), None)
    country_col = next((c for c in df.columns if "country" in c.lower()), None)
    date_col = next((c for c in df.columns if "date" in c.lower() or "day" in c.lower()), None)

    selected_industries: List[str] = []
    if industry_col is not None:
        industries = sorted(df[industry_col].dropna().astype(str).unique())
        selected_industries = st.multiselect(
            f"Filter by {industry_col}",
            options=industries,
            default=[],
            key="layoffs_industry_filter",
        )

    selected_countries: List[str] = []
    if country_col is not None:
        countries = sorted(df[country_col].dropna().astype(str).unique())
        selected_countries = st.multiselect(
            f"Filter by {country_col}",
            options=countries,
            default=[],
            key="layoffs_country_filter",
        )

    search = st.text_input("Search text (searches text columns)", key="layoffs_search_text")

    start_date = None
    end_date = None
    if date_col is not None:
        try:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            min_d = df[date_col].min()
            max_d = df[date_col].max()
            if pd.notna(min_d) and pd.notna(max_d):
                start_date, end_date = st.date_input("Date range", [min_d.date(), max_d.date()], key="layoffs_date_range")
        except Exception:
            date_col = None

    filtered = df.copy()
    mask = pd.Series(True, index=filtered.index)

    if selected_industries and industry_col is not None:
        mask &= filtered[industry_col].astype(str).isin(selected_industries)

    if selected_countries and country_col is not None:
        mask &= filtered[country_col].astype(str).isin(selected_countries)

    if search:
        search = str(search).strip()
        text_cols = filtered.select_dtypes(include=["object", "string"]).columns.tolist()
        if text_cols:
            text_mask = pd.Series(False, index=filtered.index)
            for c in text_cols:
                text_mask |= filtered[c].astype(str).str.contains(search, case=False, na=False, regex=False)
            mask &= text_mask

    if date_col is not None and start_date is not None and end_date is not None:
        date_mask = filtered[date_col].between(pd.to_datetime(start_date), pd.to_datetime(end_date))
        mask &= date_mask.fillna(False)

    filtered = filtered[mask]

    st.dataframe(filtered, use_container_width=True)

    csv = filtered.to_csv(index=False, encoding="utf-8-sig")
    st.download_button("⬇️ Скачать фильтрованные layoffs", data=csv, file_name=f"layoffs_filtered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv")


def main():
    st.set_page_config(page_title="Full Work View Dashboard", layout="wide")
    st.title("📚 Full Work View Aggregated Streamlit App")
    st.markdown(
        "Выберите приложение: HeyReach Lead Filter, SEC EDGAR Parser или Patent Lead Generation. Все функции находятся в одном интерфейсе."
    )

    app_mode = st.sidebar.radio(
        "Выберите приложение",
        ["HeyReach Leads", "SEC EDGAR Parser", "Patent Lead Generation", "Layoffs Browser"],
        index=0,
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Sample files in this project")
    for sample_file in ["sec_results_enr_contacts_found (1).csv", "patent_results(2)(1).csv", "layoffs.csv"]:
        sample_path = FULL_WORK_DIR / sample_file
        if sample_path.exists():
            st.sidebar.write(f"- {sample_file}")

    if app_mode == "HeyReach Leads":
        render_heyreach_tab()
    elif app_mode == "SEC EDGAR Parser":
        render_form_d_tab()
    elif app_mode == "Patent Lead Generation":
        render_patent_tab()
    elif app_mode == "Layoffs Browser":
        render_layoffs_tab()

if __name__ == "__main__":
    main()
