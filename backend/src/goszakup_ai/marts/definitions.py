from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mart:
    name: str
    sql: str
    indexes: tuple[str, ...] = field(default_factory=tuple)


RELIABLE_PLAN_LINKS = "('direct', 'version', 'lot', 'customer_code')"

CONTRACT_CURRENT = Mart(
    "contract_current",
    """
    SELECT DISTINCT ON (coalesce(c.root_id, c.id))
        c.*, coalesce(c.root_id, c.id) AS chain_id
    FROM core.contract c
    WHERE NOT coalesce(c.is_deleted, false)
    ORDER BY coalesce(c.root_id, c.id), c.sign_date DESC NULLS LAST, c.id DESC
    """,
    ("UNIQUE (id)", "(customer_bin)", "(chain_id)"),
)

ENSTRU_UNIT = Mart(
    "enstru_unit",
    """
    SELECT enstru_code,
           mode() WITHIN GROUP (ORDER BY unit_code) AS unit_code,
           count(*) AS plan_points
    FROM core.plan_point
    WHERE enstru_code IS NOT NULL AND unit_code IS NOT NULL AND NOT coalesce(is_deleted, false)
    GROUP BY enstru_code
    """,
    ("UNIQUE (enstru_code)",),
)

PRICE_OBSERVATION = Mart(
    "price_observation",
    """
    WITH units AS (
        SELECT cu.*,
               cc.chain_id, cc.number_sys AS contract_number, cc.sign_date, cc.fin_year,
               cc.status_id AS contract_status_id, cc.customer_bin, cc.customer_pid,
               cc.supplier_biin, cc.supplier_pid, cc.fakt_trade_method_id, cc.currency_code,
               cc.exchange_rate, cc.subject_type_id AS contract_subject_type_id,
               cc.trd_buy_id AS contract_trd_buy_id, cc.number_anno
        FROM core.contract_unit cu
        JOIN mart.contract_current cc ON cc.id = cu.contract_id
        WHERE NOT coalesce(cu.is_deleted, false)
          AND cc.status_id IS DISTINCT FROM 330
    ),
    resolved AS (
        SELECT u.*, cand.*,
               coalesce(cand.direct_id, cand.version_id, cand.lot_pp_id, cand.customer_pp_id)
                   AS resolved_pp_id
        FROM units u
        CROSS JOIN LATERAL (
            SELECT
                (SELECT p.id FROM core.plan_point p WHERE p.id = u.plan_point_id) AS direct_id,
                (SELECT p.id FROM core.plan_point p
                  WHERE p.root_record_id = u.plan_point_id
                  ORDER BY p.id DESC LIMIT 1) AS version_id,
                (SELECT p.id FROM core.lot_plan_point lp
                   JOIN core.plan_point p ON p.id = lp.plan_point_id
                  WHERE lp.lot_id = u.lot_id AND p.enstru_code = u.enstru_code
                  ORDER BY p.id DESC LIMIT 1) AS lot_pp_id,
                (SELECT p.id FROM core.plan_point p
                  WHERE p.customer_bin = u.customer_bin AND p.enstru_code = u.enstru_code
                  ORDER BY (p.year = u.fin_year) DESC, p.id DESC LIMIT 1) AS customer_pp_id
        ) cand
    ),
    priced AS (
        SELECT r.*,
               pp.unit_code AS pp_unit_code,
               coalesce(pp.unit_code, eu.unit_code) AS unit_code_resolved,
               CASE WHEN r.currency_code IS NULL OR r.currency_code = 'KZT' THEN 1
                    ELSE r.exchange_rate END AS fx
        FROM resolved r
        LEFT JOIN core.plan_point pp ON pp.id = r.resolved_pp_id
        LEFT JOIN mart.enstru_unit eu ON eu.enstru_code = r.enstru_code
    )
    SELECT
        r.id AS unit_id,
        coalesce(r.root_id, r.id) AS unit_root_id,
        r.contract_id,
        r.chain_id,
        r.contract_number,
        r.sign_date,
        date_trunc('month', r.sign_date)::date AS sign_month,
        r.fin_year,
        r.contract_status_id,
        cs.name_ru AS contract_status,
        r.contract_status_id IN (340, 350) AS is_terminated,
        r.customer_bin,
        cust.name_ru AS customer_name,
        sb.bin IS NOT NULL AS in_scope,
        r.supplier_biin,
        sup.name_ru AS supplier_name,
        coalesce(r.trd_buy_id, r.contract_trd_buy_id) AS trd_buy_id,
        r.number_anno,
        r.lot_id,
        l.lot_number,
        r.fakt_trade_method_id AS trade_method_id,
        tm.name_ru AS trade_method,
        coalesce(tm.name_ru ILIKE 'Из одного источника%', false) AS is_single_source,
        r.enstru_code,
        left(r.enstru_code, 6) AS enstru_class,
        en.name_ru AS enstru_name,
        coalesce(pp.name_ru, l.name_ru) AS item_name,
        coalesce(pp.name_clean, l.name_clean) AS item_name_clean,
        pp.desc_ru AS item_desc,
        coalesce(pp.subject_type_id, r.contract_subject_type_id) AS subject_type_id,
        r.resolved_pp_id AS plan_point_id,
        CASE WHEN r.direct_id IS NOT NULL THEN 'direct'
             WHEN r.version_id IS NOT NULL THEN 'version'
             WHEN r.lot_pp_id IS NOT NULL THEN 'lot'
             WHEN r.customer_pp_id IS NOT NULL THEN 'customer_code'
             WHEN r.unit_code_resolved IS NOT NULL THEN 'enstru_modal_unit'
             ELSE 'none' END AS plan_link,
        r.unit_code_resolved AS unit_code,
        un.name_ru AS unit_name,
        coalesce(n.canonical_code, r.unit_code_resolved) AS unit_norm_code,
        coalesce(n.factor, 1) AS unit_factor,
        coalesce(n.dimension, 'unknown') AS unit_dimension,
        coalesce(n.comparable, true) AS unit_comparable,
        r.quantity,
        r.quantity * coalesce(n.factor, 1) AS quantity_norm,
        r.item_price AS price,
        r.item_price_wnds AS price_wnds,
        r.currency_code,
        r.item_price * r.fx AS price_kzt,
        r.item_price * r.fx / nullif(coalesce(n.factor, 1), 0) AS price_norm,
        coalesce(r.total_sum, r.item_price * r.quantity) * r.fx AS amount_kzt,
        pp.price AS plan_price,
        k.kato_code,
        k.kato_source,
        rg.code AS region_code,
        rg.name_ru AS region_name,
        lc.code AS locality_code,
        lc.name_ru AS locality_name
    FROM priced r
    LEFT JOIN core.plan_point pp ON pp.id = r.resolved_pp_id
    LEFT JOIN core.ref_unit_norm n ON n.unit_code = r.unit_code_resolved
    LEFT JOIN core.ref_unit un ON un.code = r.unit_code_resolved
    LEFT JOIN core.lot l ON l.id = r.lot_id
    LEFT JOIN core.ref_dict cs ON cs.dict_name = 'contract_status' AND cs.id = r.contract_status_id
    LEFT JOIN core.ref_dict tm ON tm.dict_name = 'trade_method' AND tm.id = r.fakt_trade_method_id
    LEFT JOIN core.subject cust ON cust.pid = r.customer_pid
    LEFT JOIN core.subject sup ON sup.pid = r.supplier_pid
    LEFT JOIN meta.scope_bin sb ON sb.bin = r.customer_bin
    LEFT JOIN LATERAL (
        SELECT e.name_ru FROM core.ref_enstru e
        WHERE e.code = r.enstru_code ORDER BY e.id DESC LIMIT 1
    ) en ON true
    LEFT JOIN LATERAL (
        SELECT pk.kato_code FROM core.plan_point_kato pk
        WHERE pk.plan_point_id = pp.id AND NOT coalesce(pk.is_deleted, false)
        ORDER BY pk.quantity DESC NULLS LAST, pk.id LIMIT 1
    ) kp ON true
    CROSS JOIN LATERAL (
        SELECT coalesce(kp.kato_code, cust.kato_list[1]) AS kato_code,
               CASE WHEN kp.kato_code IS NOT NULL THEN 'plan'
                    WHEN cust.kato_list[1] IS NOT NULL THEN 'customer' END AS kato_source
    ) k
    LEFT JOIN core.ref_kato rg ON rg.code = left(k.kato_code, 2) || '0000000'
    LEFT JOIN core.ref_kato lc ON lc.code = CASE
        WHEN left(k.kato_code, 2) IN ('71', '75', '79') THEN left(k.kato_code, 2) || '0000000'
        ELSE left(k.kato_code, 4) || '00000' END
    """,
    (
        "UNIQUE (unit_id)",
        "(enstru_code, unit_norm_code)",
        "(customer_bin, fin_year)",
        "(lot_id)",
        "(contract_id)",
        "(trd_buy_id)",
        "(region_code)",
    ),
)

PRICE_BENCHMARK = Mart(
    "price_benchmark",
    f"""
    SELECT
        enstru_code,
        unit_norm_code,
        fin_year,
        region_code,
        CASE WHEN GROUPING(fin_year) = 1 THEN 'all_years'
             WHEN GROUPING(region_code) = 1 THEN 'year'
             ELSE 'year_region' END AS level,
        count(*) AS n_obs,
        count(DISTINCT customer_bin) AS n_customers,
        count(DISTINCT contract_id) AS n_contracts,
        sum(quantity_norm) AS quantity,
        sum(amount_kzt) AS amount,
        sum(price_norm * quantity_norm) / nullif(sum(quantity_norm), 0) AS wavg_price,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY price_norm) AS median_price,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY price_norm) AS p25_price,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY price_norm) AS p75_price,
        min(price_norm) AS min_price,
        max(price_norm) AS max_price
    FROM mart.price_observation
    WHERE unit_comparable
      AND plan_link IN {RELIABLE_PLAN_LINKS}
      AND price_norm > 0
      AND quantity_norm > 0
    GROUP BY GROUPING SETS (
        (enstru_code, unit_norm_code, fin_year, region_code),
        (enstru_code, unit_norm_code, fin_year),
        (enstru_code, unit_norm_code)
    )
    """,
    ("(enstru_code, unit_norm_code, level)",),
)

VOLUME_YEARLY = Mart(
    "volume_yearly",
    """
    WITH plan AS (
        SELECT p.customer_bin, p.enstru_code,
               coalesce(n.canonical_code, p.unit_code) AS unit_norm_code,
               p.year,
               sum(p.quantity * coalesce(n.factor, 1)) AS plan_quantity,
               sum(p.amount) AS plan_amount,
               count(*) AS plan_points
        FROM core.plan_point p
        JOIN meta.scope_bin sb ON sb.bin = p.customer_bin
        LEFT JOIN core.ref_unit_norm n ON n.unit_code = p.unit_code
        LEFT JOIN core.ref_dict st ON st.dict_name = 'plan_point_status' AND st.id = p.status_id
        WHERE NOT coalesce(p.is_deleted, false)
          AND coalesce(st.name_ru, '') <> 'Изменен'
        GROUP BY 1, 2, 3, 4
    ),
    fact AS (
        SELECT customer_bin, enstru_code, unit_norm_code, fin_year AS year,
               sum(quantity_norm) AS fact_quantity,
               sum(amount_kzt) AS fact_amount,
               count(*) AS fact_units
        FROM mart.price_observation
        WHERE in_scope
        GROUP BY 1, 2, 3, 4
    )
    SELECT *
    FROM plan FULL JOIN fact USING (customer_bin, enstru_code, unit_norm_code, year)
    """,
    ("(customer_bin, enstru_code)", "(enstru_code)"),
)

PROCUREMENT_EFFICIENCY = Mart(
    "procurement_efficiency",
    """
    WITH obs AS (
        SELECT * FROM mart.price_observation WHERE in_scope
    ),
    contracts AS (
        SELECT customer_bin, fin_year AS year,
               sum(amount_kzt) AS contract_amount,
               sum(amount_kzt) FILTER (WHERE is_single_source) AS single_source_amount,
               sum(price * quantity) FILTER (WHERE plan_link = 'direct' AND plan_price > 0)
                   AS matched_fact_amount,
               sum(plan_price * quantity) FILTER (WHERE plan_link = 'direct' AND plan_price > 0)
                   AS matched_plan_amount,
               count(DISTINCT contract_id) AS contracts,
               count(DISTINCT supplier_biin) AS suppliers
        FROM obs GROUP BY 1, 2
    ),
    supplier_share AS (
        SELECT customer_bin, year, sum(share * share) AS supplier_hhi
        FROM (
            SELECT customer_bin, fin_year AS year,
                   sum(amount_kzt) / nullif(sum(sum(amount_kzt)) OVER (
                       PARTITION BY customer_bin, fin_year), 0) AS share
            FROM obs GROUP BY customer_bin, fin_year, supplier_biin
        ) s
        GROUP BY 1, 2
    ),
    lots AS (
        SELECT l.customer_bin, t.fin_years[1] AS year,
               count(*) AS lots,
               count(*) FILTER (WHERE l.status_id = 370) AS lots_failed,
               count(*) FILTER (WHERE l.status_id IN (410, 430)) AS lots_cancelled
        FROM core.lot l
        JOIN meta.scope_bin sb ON sb.bin = l.customer_bin
        JOIN core.trd_buy t ON t.id = l.trd_buy_id
        GROUP BY 1, 2
    ),
    timing AS (
        SELECT c.customer_bin, c.fin_year AS year,
               avg(extract(epoch FROM c.sign_date - t.publish_date) / 86400)
                   AS avg_days_publish_to_sign
        FROM mart.contract_current c
        JOIN meta.scope_bin sb ON sb.bin = c.customer_bin
        JOIN core.trd_buy t ON t.id = c.trd_buy_id
        WHERE c.sign_date >= t.publish_date
        GROUP BY 1, 2
    ),
    plan AS (
        SELECT customer_bin, year, sum(plan_amount) AS plan_amount
        FROM mart.volume_yearly GROUP BY 1, 2
    )
    SELECT
        c.customer_bin,
        c.year,
        p.plan_amount,
        c.contract_amount,
        c.contracts,
        c.suppliers,
        1 - c.matched_fact_amount / nullif(c.matched_plan_amount, 0) AS economy_share,
        c.single_source_amount / nullif(c.contract_amount, 0) AS single_source_share,
        s.supplier_hhi,
        lt.lots,
        lt.lots_failed::numeric / nullif(lt.lots, 0) AS lots_failed_share,
        lt.lots_cancelled::numeric / nullif(lt.lots, 0) AS lots_cancelled_share,
        tg.avg_days_publish_to_sign
    FROM contracts c
    LEFT JOIN plan p USING (customer_bin, year)
    LEFT JOIN supplier_share s USING (customer_bin, year)
    LEFT JOIN lots lt USING (customer_bin, year)
    LEFT JOIN timing tg USING (customer_bin, year)
    """,
    ("UNIQUE (customer_bin, year)",),
)

MARTS: tuple[Mart, ...] = (
    CONTRACT_CURRENT,
    ENSTRU_UNIT,
    PRICE_OBSERVATION,
    PRICE_BENCHMARK,
    VOLUME_YEARLY,
    PROCUREMENT_EFFICIENCY,
)
