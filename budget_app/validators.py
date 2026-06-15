from datetime import datetime

from budget_app.errors import BudgetAppError

class Validator:
    @staticmethod
    def validate_category_name(name: str) -> str:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise BudgetAppError(
                "카테고리 이름이 올바르지 않습니다.",
                "힌트: 공백이 아닌 한 글자 이상의 이름을 입력해주세요."
            )
        return cleaned_name

    @staticmethod
    def validate_date(value: str) -> str:
        cleaned_value = value.strip()
        try:
            datetime.strptime(cleaned_value, "%Y-%m-%d")
        except ValueError:
            raise BudgetAppError(
                "날짜 형식이 올바르지 않습니다.",
                "YYYY-MM-DD 형식으로 입력해주세요. 예: 2023-12-22"
            )
        return cleaned_value

    @staticmethod
    def validate_month(value: str) -> str:
        cleaned_value = value.strip()
        try:
            datetime.strptime(cleaned_value, "%Y-%m")
        except ValueError:
            raise BudgetAppError(
                "월 형식이 올바르지 않습니다.",
                "YYYY-MM 형식으로 입력해주세요. 예: 2026-06"
            )
        return cleaned_value

    @staticmethod
    def validate_type(value: str) -> str:
        cleaned_value = value.strip().lower()
        if cleaned_value not in ("income", "expense"):
            raise BudgetAppError(
                "타입이 올바르지 않습니다.",
                "income 또는 expense 중 하나를 입력해주세요."
            )
        return cleaned_value

    @staticmethod
    def validate_amount(value: str) -> int:
        cleaned_value = value.strip()
        try:
            amount = int(cleaned_value)
        except ValueError:
            raise BudgetAppError(
                "금액이 올바르지 않습니다.",
                "0보다 큰 정수를 입력해주세요."
            )
        if amount <= 0:
            raise BudgetAppError(
                "금액이 올바르지 않습니다.",
                "0보다 큰 정수를 입력해주세요."
            )
        return amount
