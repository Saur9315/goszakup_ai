from dataclasses import dataclass, field

from goszakup_ai.analytics.stats import HETEROGENEOUS_MAD_LOG
from goszakup_ai.transform.text import desc_text_sql


@dataclass(frozen=True)
class Mart:
    name: str
    sql: str
    indexes: tuple[str, ...] = field(default_factory=tuple)


RELIABLE_PLAN_LINKS = "('direct', 'version', 'lot', 'customer_code')"
MIN_SUBCLASS_PEERS = 5
PP_DESC_KEY = f"md5({desc_text_sql('pp.extra_desc_ru')})"

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
    f"""
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
        CASE WHEN pp.extra_desc_ru IS NOT NULL THEN {PP_DESC_KEY} END AS desc_key,
        sc.subclass,
        sc.label AS subclass_label,
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
        unn.name_ru AS unit_norm_name,
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
    LEFT JOIN core.ref_unit unn ON unn.code = coalesce(n.canonical_code, r.unit_code_resolved)
    LEFT JOIN core.lot l ON l.id = r.lot_id
    LEFT JOIN core.ref_dict cs ON cs.dict_name = 'contract_status' AND cs.id = r.contract_status_id
    LEFT JOIN core.ref_dict tm ON tm.dict_name = 'trade_method' AND tm.id = r.fakt_trade_method_id
    LEFT JOIN core.subject cust ON cust.pid = r.customer_pid
    LEFT JOIN core.subject sup ON sup.pid = r.supplier_pid
    LEFT JOIN meta.scope_bin sb ON sb.bin = r.customer_bin
    LEFT JOIN core.item_subclass sc
           ON sc.enstru_code = r.enstru_code
          AND sc.text_key = {PP_DESC_KEY}
          AND (r.direct_id IS NOT NULL OR r.version_id IS NOT NULL OR r.lot_pp_id IS NOT NULL)
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

CPI_INDEX = Mart(
    "cpi_index",
    """
    SELECT month, cpi_mom_pct,
           100 * exp(sum(ln(1 + cpi_mom_pct / 100)) OVER (ORDER BY month)) AS idx
    FROM core.ref_cpi
    WHERE cpi_mom_pct IS NOT NULL
    """,
    ("UNIQUE (month)",),
)

REGION_PRICE_INDEX = Mart(
    "region_price_index",
    f"""
    WITH base AS (
        SELECT enstru_code, unit_norm_code, region_code, price_norm
        FROM mart.price_observation
        WHERE unit_comparable AND plan_link IN {RELIABLE_PLAN_LINKS}
          AND price_norm > 0 AND region_code IS NOT NULL
    ),
    national AS (
        SELECT enstru_code, unit_norm_code,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY price_norm) AS med
        FROM base GROUP BY 1, 2
        HAVING count(DISTINCT region_code) >= 2
    ),
    regional AS (
        SELECT enstru_code, unit_norm_code, region_code,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY price_norm) AS med
        FROM base GROUP BY 1, 2, 3
        HAVING count(*) >= 3
    ),
    ratios AS (
        SELECT r.region_code, ln(r.med / n.med) AS log_ratio
        FROM regional r JOIN national n USING (enstru_code, unit_norm_code)
    )
    SELECT region_code,
           count(*) AS n_codes,
           exp(percentile_cont(0.5) WITHIN GROUP (ORDER BY log_ratio)) AS raw_k,
           exp(count(*)::float8 / (count(*) + 20)
               * percentile_cont(0.5) WITHIN GROUP (ORDER BY log_ratio)) AS k
    FROM ratios
    GROUP BY region_code
    """,
    ("UNIQUE (region_code)",),
)

SEASON_INDEX = Mart(
    "season_index",
    f"""
    WITH base AS (
        SELECT o.enstru_code, o.unit_norm_code, o.fin_year,
               extract(month FROM o.sign_date)::int AS month,
               o.price_norm * 100 / coalesce(ci.idx, 100) AS real_price
        FROM mart.price_observation o
        LEFT JOIN mart.cpi_index ci ON ci.month = o.sign_month
        WHERE o.unit_comparable AND o.plan_link IN {RELIABLE_PLAN_LINKS}
          AND o.price_norm > 0 AND o.sign_date IS NOT NULL
    ),
    yearly AS (
        SELECT enstru_code, unit_norm_code, fin_year,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY real_price) AS med
        FROM base GROUP BY 1, 2, 3
        HAVING count(*) >= 6
    ),
    ratios AS (
        SELECT b.month, ln(b.real_price / y.med) AS log_ratio
        FROM base b JOIN yearly y USING (enstru_code, unit_norm_code, fin_year)
    )
    SELECT month,
           count(*) AS n_obs,
           exp(percentile_cont(0.5) WITHIN GROUP (ORDER BY log_ratio)) AS raw_factor,
           exp(count(*)::float8 / (count(*) + 500)
               * percentile_cont(0.5) WITHIN GROUP (ORDER BY log_ratio)) AS factor
    FROM ratios
    GROUP BY month
    """,
    ("UNIQUE (month)",),
)

PRICE_ANOMALY = Mart(
    "price_anomaly",
    f"""
    WITH obs AS (
        SELECT o.*,
               o.price_norm * 100 / coalesce(ci.idx, 100) AS real_price,
               ci.idx AS cpi_idx
        FROM mart.price_observation o
        LEFT JOIN mart.cpi_index ci ON ci.month = o.sign_month
        WHERE o.unit_comparable AND o.plan_link IN {RELIABLE_PLAN_LINKS}
          AND o.price_norm > 0 AND o.quantity_norm > 0
    ),
    grp AS (
        SELECT enstru_code, unit_norm_code,
               count(*) AS n,
               count(DISTINCT customer_bin) AS n_customers,
               sum(real_price * quantity_norm) AS spq,
               sum(quantity_norm) AS sq,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY ln(real_price)) AS med_log
        FROM obs GROUP BY 1, 2
    ),
    disp AS (
        SELECT o.enstru_code, o.unit_norm_code,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(ln(o.real_price) - g.med_log))
                   AS mad_log
        FROM obs o JOIN grp g USING (enstru_code, unit_norm_code)
        GROUP BY 1, 2
    ),
    sgrp AS (
        SELECT enstru_code, unit_norm_code, subclass,
               count(*) AS n,
               count(DISTINCT customer_bin) AS n_customers,
               sum(real_price * quantity_norm) AS spq,
               sum(quantity_norm) AS sq,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY ln(real_price)) AS med_log
        FROM obs WHERE subclass IS NOT NULL GROUP BY 1, 2, 3
    ),
    sdisp AS (
        SELECT o.enstru_code, o.unit_norm_code, o.subclass,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(ln(o.real_price) - g.med_log))
                   AS mad_log
        FROM obs o JOIN sgrp g USING (enstru_code, unit_norm_code, subclass)
        GROUP BY 1, 2, 3
    ),
    scored AS (
        SELECT o.*,
               x.peer_group,
               x.n - 1 AS peer_n,
               x.n_customers,
               (x.spq - o.real_price * o.quantity_norm) / nullif(x.sq - o.quantity_norm, 0)
                   AS peer_wavg_real,
               exp(x.med_log) AS group_median_real,
               (ln(o.real_price) - x.med_log) / nullif(1.4826 * x.mad_log, 0) AS robust_z,
               x.mad_log AS group_mad_log
        FROM obs o
        JOIN grp g USING (enstru_code, unit_norm_code)
        JOIN disp d USING (enstru_code, unit_norm_code)
        LEFT JOIN sgrp s
               ON s.enstru_code = o.enstru_code AND s.unit_norm_code = o.unit_norm_code
              AND s.subclass = o.subclass
        LEFT JOIN sdisp sd
               ON sd.enstru_code = o.enstru_code AND sd.unit_norm_code = o.unit_norm_code
              AND sd.subclass = o.subclass
        CROSS JOIN LATERAL (
            SELECT coalesce(
                       s.n > {MIN_SUBCLASS_PEERS} AND (
                           abs(s.med_log - g.med_log) > {HETEROGENEOUS_MAD_LOG}
                           OR (d.mad_log > {HETEROGENEOUS_MAD_LOG} AND sd.mad_log < d.mad_log)
                       ),
                       false
                   ) AS use_subclass
        ) u
        CROSS JOIN LATERAL (
            SELECT CASE WHEN u.use_subclass THEN 'subclass' ELSE 'code' END AS peer_group,
                   CASE WHEN u.use_subclass THEN s.n ELSE g.n END AS n,
                   CASE WHEN u.use_subclass THEN s.n_customers ELSE g.n_customers END
                       AS n_customers,
                   CASE WHEN u.use_subclass THEN s.spq ELSE g.spq END AS spq,
                   CASE WHEN u.use_subclass THEN s.sq ELSE g.sq END AS sq,
                   CASE WHEN u.use_subclass THEN s.med_log ELSE g.med_log END AS med_log,
                   CASE WHEN u.use_subclass THEN sd.mad_log ELSE d.mad_log END AS mad_log
        ) x
        WHERE o.in_scope
    )
    SELECT unit_id, contract_id, chain_id, lot_id, lot_number, trd_buy_id, contract_number,
           customer_bin, customer_name, supplier_biin, supplier_name, sign_date, fin_year,
           enstru_code, enstru_name, item_name, unit_norm_code, unit_name, unit_dimension,
           plan_link, quantity_norm, price_norm, real_price, amount_kzt, region_name,
           locality_name, trade_method, is_single_source, cpi_idx IS NOT NULL AS cpi_adjusted,
           peer_n, n_customers, peer_wavg_real, group_median_real, robust_z, group_mad_log,
           peer_group, subclass, subclass_label,
           real_price / nullif(peer_wavg_real, 0) - 1 AS deviation,
           (real_price - peer_wavg_real) * quantity_norm * coalesce(cpi_idx, 100) / 100
               AS overpayment_kzt
    FROM scored
    """,
    ("UNIQUE (unit_id)", "(customer_bin, fin_year)", "(enstru_code)", "(deviation)"),
)

VOLUME_ANOMALY = Mart(
    "volume_anomaly",
    """
    WITH v AS (
        SELECT y.customer_bin, y.enstru_code, coalesce(y.unit_norm_code, '') AS unit_norm_code,
               y.year,
               coalesce(y.plan_quantity, y.fact_quantity) AS quantity,
               coalesce(y.plan_amount, y.fact_amount) AS amount,
               CASE WHEN y.plan_quantity IS NOT NULL THEN 'plan' ELSE 'fact' END AS source
        FROM mart.volume_yearly y
        LEFT JOIN core.ref_unit_norm n ON n.canonical_code = y.unit_norm_code
            AND n.unit_code = y.unit_norm_code
        WHERE coalesce(y.plan_quantity, y.fact_quantity) > 0
          AND coalesce(n.comparable, true)
    ),
    baseline AS (
        SELECT c.customer_bin, c.enstru_code, c.unit_norm_code, c.year,
               avg(p.quantity) AS baseline_quantity,
               avg(p.amount) AS baseline_amount,
               count(*) AS baseline_years
        FROM v c
        JOIN v p ON p.customer_bin = c.customer_bin AND p.enstru_code = c.enstru_code
                AND p.unit_norm_code = c.unit_norm_code AND p.year < c.year
        GROUP BY 1, 2, 3, 4
    ),
    ratios AS (
        SELECT v.*, b.baseline_quantity, b.baseline_amount, b.baseline_years,
               v.quantity / b.baseline_quantity AS ratio
        FROM v JOIN baseline b USING (customer_bin, enstru_code, unit_norm_code, year)
        WHERE b.baseline_quantity > 0
    ),
    peers AS (
        SELECT enstru_code, unit_norm_code, year,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY ratio) AS peer_ratio,
               count(*) AS peer_n
        FROM ratios GROUP BY 1, 2, 3
    )
    SELECT r.customer_bin, sb.name_ru AS customer_name, r.enstru_code, en.name_ru AS enstru_name,
           nullif(r.unit_norm_code, '') AS unit_norm_code, un.name_ru AS unit_name,
           r.year, r.source,
           r.quantity, r.amount, r.baseline_quantity, r.baseline_amount, r.baseline_years,
           r.ratio,
           p.peer_ratio, p.peer_n - 1 AS peer_n,
           CASE WHEN p.peer_n >= 4 THEN r.ratio / nullif(p.peer_ratio, 0) END AS excess_ratio,
           (r.quantity - r.baseline_quantity) * r.amount / nullif(r.quantity, 0) AS extra_amount
    FROM ratios r
    JOIN peers p USING (enstru_code, unit_norm_code, year)
    LEFT JOIN meta.scope_bin sb ON sb.bin = r.customer_bin
    LEFT JOIN core.ref_unit un ON un.code = r.unit_norm_code
    LEFT JOIN LATERAL (
        SELECT e.name_ru FROM core.ref_enstru e
        WHERE e.code = r.enstru_code ORDER BY e.id DESC LIMIT 1
    ) en ON true
    """,
    ("(customer_bin, year)", "(ratio)", "(enstru_code)"),
)

ITEM_CATALOG = Mart(
    "item_catalog",
    """
    SELECT enstru_code, name, sum(n_obs) AS n_obs, sum(n_scope) AS n_scope, sum(amount) AS amount
    FROM (
        SELECT enstru_code, item_name_clean AS name, count(*) AS n_obs,
               count(*) FILTER (WHERE in_scope) AS n_scope, sum(amount_kzt) AS amount
        FROM mart.price_observation
        WHERE enstru_code IS NOT NULL AND item_name_clean IS NOT NULL
        GROUP BY 1, 2
        UNION ALL
        SELECT code, lower(name_ru), 0, 0, 0 FROM core.ref_enstru WHERE name_ru IS NOT NULL
    ) names
    GROUP BY enstru_code, name
    """,
    ("USING gin (name gin_trgm_ops)", "(enstru_code)"),
)

CUSTOMER_COVERAGE = Mart(
    "customer_coverage",
    """
    WITH yearly AS (
        SELECT sb.bin AS customer_bin, sb.name_ru AS customer_name, y.year,
               count(c.id) AS contracts, coalesce(sum(c.contract_sum), 0) AS amount
        FROM meta.scope_bin sb
        CROSS JOIN (SELECT DISTINCT fin_year AS year FROM mart.contract_current
                    WHERE fin_year BETWEEN 2024 AND 2026) y
        LEFT JOIN mart.contract_current c ON c.customer_bin = sb.bin AND c.fin_year = y.year
        GROUP BY 1, 2, 3
    )
    SELECT *,
           lag(contracts) OVER (PARTITION BY customer_bin ORDER BY year) AS prev_contracts
    FROM yearly
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
    CPI_INDEX,
    REGION_PRICE_INDEX,
    SEASON_INDEX,
    PRICE_ANOMALY,
    VOLUME_ANOMALY,
    ITEM_CATALOG,
    CUSTOMER_COVERAGE,
)
