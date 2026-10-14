from dataclasses import dataclass

SUBJECT_FIELDS = """
pid bin iin nameRu nameKz fullNameRu customer supplier organizer qvazi markNationalCompany
markSmallEmployer typeSupplier katoList parentSubject countryCode lastUpdateDate indexDate
"""

PLAN_POINT_FIELDS = """
id rootrecordId sysSubjectsId sysOrganizatorId subjectBiin nameRu nameKz descRu descKz
extraDescRu extraDescKz refTradeMethodsId refUnitsCode count price amount refMonthsId
refPlnPointStatusId plnPointYear refSubjectTypeId refEnstruCode refEnstruId refFinsourceId
refPointTypeId isQvazi dateCreate timestamp isDeleted isActive indexDate
PlansKato {
  id refKatoCode refCountriesCode fullDeliveryPlaceNameRu fullDeliveryPlaceNameKz count
  isActive isDeleted
}
RefEnstru { id code nameRu nameKz descRu parentId level edizm mkei }
"""

CONTRACT_FIELDS = f"""
id rootId parentId refContractTypeId contractNumber contractNumberSys trdBuyId trdBuyNumberAnno
customerId customerBin supplierId supplierBiin refContractStatusId faktTradeMethodsId
refSubjectTypeId finYear refContractYearTypeId refFinsourceId signDate planExecDate
faktExecDate contractEndDate contractSum contractSumWnds faktSum faktSumWnds withNds
refCurrencyCode exchangeRate refContractCancelId deleted crdate lastUpdateDate indexDate
ContractUnits {{
  id rootId parentId lotId plnPointId trdBuyId refEnstruCode itemPrice itemPriceWnds quantity
  totalSum totalSumWnds contractSum contractSumWnds factSum factSumWnds refContractStatusId
  executed deleted execPlanDate execFaktDate crdate indexDate
}}
Supplier {{ {SUBJECT_FIELDS} }}
Customer {{ {SUBJECT_FIELDS} }}
"""

LOT_FIELDS = """
id lotNumber refLotStatusId lastUpdateDate unionLots count amount nameRu nameKz descriptionRu
descriptionKz customerId customerBin trdBuyNumberAnno trdBuyId dumping refTradeMethodsId
refBuyTradeMethodsId pointList enstruList plnPointKatoList isConstructionWork isDeleted indexDate
"""

TRD_BUY_FIELDS = """
id numberAnno nameRu nameKz totalSum countLots refTradeMethodsId refSubjectTypeId refBuyStatusId
refTypeTradeId orgPid orgBin biinSupplier parentId publishDate startDate endDate itogiDatePublic
finYear kato isConstructionWork lastUpdateDate indexDate
"""


@dataclass(frozen=True)
class EntitySpec:
    name: str
    root_field: str
    filter_type: str
    fields: str
    key: str = "id"

    @property
    def query(self) -> str:
        return (
            f"query($filter: {self.filter_type}, $after: Int) {{ "
            f"{self.root_field}(filter: $filter, limit: 200, after: $after) {{ {self.fields} }} }}"
        )


SUBJECT = EntitySpec("subject", "Subjects", "SubjectFiltersInput", SUBJECT_FIELDS, key="pid")
PLAN_POINT = EntitySpec("plan_point", "Plans", "PlansFiltersInput", PLAN_POINT_FIELDS)
CONTRACT = EntitySpec("contract", "Contract", "ContractFiltersInput", CONTRACT_FIELDS)
LOT = EntitySpec("lot", "Lots", "LotsFiltersInput", LOT_FIELDS)
TRD_BUY = EntitySpec("trd_buy", "TrdBuy", "TrdBuyFiltersInput", TRD_BUY_FIELDS)
