import numpy as np

from goszakup_ai.analytics.anomalies import isolation_outliers


def test_isolation_flags_isolated_point() -> None:
    rng = np.random.default_rng(0)
    normal = rng.normal(0, 0.2, size=(300, 3))
    features = np.vstack([normal, [[6.0, 5.0, 4.0]]])

    scores, outliers = isolation_outliers(features, share=0.02)

    assert outliers[-1]
    assert scores[-1] == scores.max()
    assert outliers.sum() <= 0.03 * len(features)


def test_isolation_skips_small_samples() -> None:
    scores, outliers = isolation_outliers(np.ones((5, 3)))

    assert not outliers.any()
    assert (scores == 0).all()
