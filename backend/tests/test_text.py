import pytest

from goszakup_ai.transform.text import clean_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Поставка: «Бумага офисная А4»", "бумага офисная а4"),
        ("Приобретение  перчаток , лот № 12", "перчаток"),
        ("Плазма свежезамороженная №3", "плазма свежезамороженная"),
        ("Шприц 5 мл", "шприц 5 мл"),
        ("Бyмaгa", "бумага"),
        ("Қағаз ақ тусті", "қағаз ақ тусті"),
        ("Kағаз", "кағаз"),
        ("HP LaserJet 1020", "hp laserjet 1020"),
        ("   ", None),
        (None, None),
    ],
)
def test_clean_name(raw: str | None, expected: str | None) -> None:
    assert clean_name(raw) == expected
