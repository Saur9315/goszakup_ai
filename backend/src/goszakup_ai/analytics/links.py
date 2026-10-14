PORTAL = "https://goszakup.gov.kz/ru"


def contract_url(contract_id: int | None) -> str | None:
    return f"{PORTAL}/egzcontract/cpublic/show/{contract_id}" if contract_id else None


def announce_url(trd_buy_id: int | None) -> str | None:
    return f"{PORTAL}/announce/index/{trd_buy_id}" if trd_buy_id else None
