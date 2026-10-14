from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    name: str
    entity: str
    severity: str
    description: str
    failed_where: str
    source: str = "mart.price_observation"
    key: str = "unit_id"


def check_sql(check: Check) -> str:
    return f"""
    SELECT count(*) FILTER (WHERE {check.failed_where}) AS failed,
           count(*) AS total,
           coalesce(
               (array_agg({check.key} ORDER BY {check.key})
                    FILTER (WHERE {check.failed_where}))[1:10],
               '{{}}'
           ) AS sample
    FROM {check.source}
    """


FRESHNESS_SQL = """
SELECT (coalesce(extract(epoch FROM now() - max(finished_at)) / 3600, 1e9) > 24)::int AS failed,
       1 AS total,
       ARRAY[round(coalesce(extract(epoch FROM now() - max(finished_at)) / 3600, -1)::numeric, 1)]
           AS sample
FROM meta.sync_run
WHERE status = 'ok' AND command LIKE 'ingest scope%'
"""

CHECKS: tuple[Check, ...] = (
    Check(
        "price_non_positive",
        "contract_unit",
        "error",
        "Цена за единицу не задана или не положительная",
        "price IS NULL OR price <= 0",
    ),
    Check(
        "quantity_non_positive",
        "contract_unit",
        "error",
        "Количество не задано или не положительное",
        "quantity IS NULL OR quantity <= 0",
    ),
    Check(
        "vat_price_below_net",
        "contract_unit",
        "error",
        "Цена с НДС меньше цены без НДС",
        "price_wnds < price",
    ),
    Check(
        "sum_mismatch",
        "contract_unit",
        "warning",
        "Сумма позиции расходится с ценой × количество более чем на 1%",
        "abs(price_kzt * quantity - amount_kzt) > 0.01 * nullif(abs(amount_kzt), 0)",
    ),
    Check(
        "plan_point_unresolved",
        "contract_unit",
        "warning",
        "Позиция договора не связана с пунктом плана (нет единицы и места поставки)",
        "plan_link = 'none'",
    ),
    Check(
        "unit_imputed",
        "contract_unit",
        "info",
        "Единица измерения восстановлена по типичной для кода ЕНС ТРУ",
        "plan_link = 'enstru_modal_unit'",
    ),
    Check(
        "unit_not_normalized",
        "contract_unit",
        "warning",
        "Единица измерения отсутствует в таблице нормализации",
        "unit_dimension = 'unknown'",
    ),
    Check(
        "unit_not_comparable",
        "contract_unit",
        "info",
        "Услуги и работы: цена за единицу несопоставима",
        "NOT unit_comparable",
    ),
    Check(
        "plan_contract_price_ratio_extreme",
        "contract_unit",
        "warning",
        "Цена договора отличается от плановой более чем в 10 раз (вероятна ошибка единиц)",
        "plan_link = 'direct' AND plan_price > 0 AND price > 0"
        " AND (price / plan_price > 10 OR price / plan_price < 0.1)",
    ),
    Check(
        "kato_from_customer",
        "contract_unit",
        "info",
        "Место поставки взято из адреса заказчика, а не из пункта плана",
        "kato_source = 'customer'",
    ),
    Check(
        "kato_missing",
        "contract_unit",
        "warning",
        "Место поставки неизвестно",
        "kato_code IS NULL",
    ),
    Check(
        "currency_not_kzt",
        "contract_unit",
        "info",
        "Договор в иностранной валюте, цена пересчитана по курсу договора",
        "currency_code IS NOT NULL AND currency_code <> 'KZT'",
    ),
    Check(
        "cpi_month_missing",
        "contract_unit",
        "info",
        "Для месяца подписания ещё нет опубликованного ИПЦ: инфляционная поправка неполная",
        "sign_month IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM mart.cpi_index ci WHERE ci.month = mart.price_observation.sign_month)",
    ),
    Check(
        "customer_coverage_drop",
        "customer",
        "warning",
        "Число договоров организации за год упало более чем на 80% к прошлому году "
        "(вероятно, закупки ведутся вне портала goszakup)",
        "prev_contracts >= 20 AND contracts < 0.2 * prev_contracts",
        source="mart.customer_coverage",
        key="customer_bin",
    ),
    Check(
        "plan_point_without_enstru",
        "plan_point",
        "warning",
        "Пункт плана без кода ЕНС ТРУ",
        "enstru_code IS NULL",
        source="core.plan_point",
        key="id",
    ),
    Check(
        "lot_without_trd_buy",
        "lot",
        "warning",
        "Лот ссылается на отсутствующее объявление",
        "trd_buy_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM core.trd_buy t WHERE t.id = core.lot.trd_buy_id)",
        source="core.lot",
        key="id",
    ),
)
