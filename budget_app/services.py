import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from budget_app.storage import Storage
from budget_app.models import Budget, Category, Transaction
from budget_app.errors import BudgetAppError

class CategoryService:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def add_category(self, name: str) -> Category:    
        for cat in self.storage.load_categories_stream():
            if cat.name == name:
                raise BudgetAppError(
                    f"카테고리 '{name}'은(는) 이미 존재합니다.",
                    "다른 이름을 사용하거나 'category list' 명령어로 확인하세요."
                )
        
        new_category = Category(name=name)
        self.storage.append_category(new_category)
        return new_category

    def list_categories(self) -> List[Category]:
        return list(self.storage.load_categories_stream())

    def remove_category(self, name: str) -> None:
        all_categories = self.list_categories()
        exists = any(cat.name == name for cat in all_categories)
        if not exists:
            raise BudgetAppError(
                f"삭제하려는 카테고리 '{name}'이(가) 존재하지 않습니다.",
                "'category list' 명령어로 정확한 이름을 확인하세요."
            )

        if self.storage.is_category_used_in_transactions(name):
            raise BudgetAppError(
                f"카테고리 '{name}'을(를) 사용하는 거래 내역이 존재하여 삭제할 수 없습니다.",
                "해당 카테고리가 포함된 거래를 먼저 삭제하거나 수정해야 합니다."
            )

        updated_categories = [cat for cat in all_categories if cat.name != name]
        self.storage.overwrite_categories(updated_categories)

    def exists_category(self, name: str) -> bool:
        return any(cat.name == name for cat in self.storage.load_categories_stream())


class BudgetService:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def set_budget(self, month: str, amount: int) -> Budget:
        budget = Budget(month=month, amount=amount)
        return self.storage.set_budget(budget)

    def get_budget(self, month: str) -> Optional[Budget]:
        return self.storage.get_budget(month)

class TransactionService:
    CSV_FIELDS = ["date", "type", "category", "amount", "memo", "tags"]

    def __init__(self, storage: Storage, category_service: 'CategoryService') -> None:
        self.storage = storage
        self.category_service = category_service

    def add_transaction(
        self,
        amount: int,
        category_name: str,
        type: str,
        date: str,
        memo: Optional[str] = None,
        tags: Optional[str] = None
        ) -> Transaction:

        if not self.category_service.exists_category(category_name):
            raise BudgetAppError(
                f"카테고리 '{category_name}'이(가) 존재하지 않습니다.",
                "거래를 추가하기 전에 해당 카테고리를 먼저 추가하세요."
            )
        
        category = Category(name=category_name)
        transaction = Transaction(
            type=type,
            date=date,
            amount=amount,
            category=category,
            memo= memo.strip() if memo and memo.strip() else None,
            tags=[
                tag.strip()
                for tag in tags.split(",")
                if tag.strip()
            ] if tags and tags.strip() else []
        )
        # transaction 처리
        offset = self.storage.append_transaction(transaction)
        self.storage.append_transaction_date_index(transaction, offset)
        
        return transaction

    def delete_transaction(self, transaction_id: str) -> bool:
        transactions = list(self.storage.load_transactions_stream())
        updated_transactions = [
            transaction
            for transaction in transactions
            if transaction.id != transaction_id
        ]
        if len(updated_transactions) == len(transactions):
            return False

        self.storage.overwrite_transactions(updated_transactions)
        return True

    def update_transaction(
        self,
        transaction_id: str,
        date: Optional[str] = None,
        type: Optional[str] = None,
        category_name: Optional[str] = None,
        amount: Optional[int] = None,
        memo: Optional[str] = None,
        tags: Optional[str] = None
    ) -> Optional[Transaction]:
        transactions = list(self.storage.load_transactions_stream())
        updated_transaction: Optional[Transaction] = None
        updated_transactions: List[Transaction] = []

        if category_name and not self.category_service.exists_category(category_name):
            raise BudgetAppError(
                f"카테고리 '{category_name}'이(가) 존재하지 않습니다.",
                "거래를 수정하기 전에 해당 카테고리를 먼저 추가하세요."
            )

        for transaction in transactions:
            if transaction.id != transaction_id:
                updated_transactions.append(transaction)
                continue

            updated_transaction = Transaction(
                id=transaction.id,
                type=type if type is not None else transaction.type,
                date=date if date is not None else transaction.date,
                amount=amount if amount is not None else transaction.amount,
                category=Category(
                    name=category_name if category_name is not None else transaction.category.name
                ),
                memo=memo if memo is not None else transaction.memo,
                tags=[
                    tag.strip()
                    for tag in tags.split(",")
                    if tag.strip()
                ] if tags is not None else transaction.tags
            )
            updated_transactions.append(updated_transaction)

        if updated_transaction is None:
            return None

        self.storage.overwrite_transactions(updated_transactions)
        return updated_transaction

    def import_transactions_from_csv(self, csv_path: str) -> int:
        new_transactions = self._read_transactions_from_csv(csv_path)
        transactions = list(self.storage.load_transactions_stream())
        transactions.extend(new_transactions)
        self.storage.overwrite_transactions(transactions)
        return len(new_transactions)

    def export_transactions_to_csv(
        self,
        out_path: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> int:
        output_path = Path(out_path)
        temp_path = output_path.with_name(f"{output_path.name}.tmp")
        count = 0

        try:
            with open(temp_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
                writer.writeheader()
                for transaction in self.search_transactions(
                    from_date=from_date,
                    to_date=to_date
                ):
                    writer.writerow(self._transaction_to_csv_row(transaction))
                    count += 1
            temp_path.replace(output_path)
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise e

        return count

    def _read_transactions_from_csv(self, csv_path: str) -> List[Transaction]:
        transactions: List[Transaction] = []
        try:
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                self._validate_csv_header(reader.fieldnames)
                for row_number, row in enumerate(reader, start=2):
                    transactions.append(self._csv_row_to_transaction(row, row_number))
        except FileNotFoundError:
            raise BudgetAppError(
                f"CSV 파일을 찾을 수 없습니다: {csv_path}",
                "가져올 CSV 파일 경로를 확인해주세요."
            )
        return transactions

    def _validate_csv_header(self, fieldnames: Optional[List[str]]) -> None:
        if not fieldnames:
            raise BudgetAppError(
                "CSV 헤더가 없습니다.",
                "date,type,category,amount,memo,tags 헤더를 포함해주세요."
            )

        missing_fields = [
            field
            for field in self.CSV_FIELDS
            if field not in fieldnames
        ]
        if missing_fields:
            raise BudgetAppError(
                f"CSV 필수 컬럼이 누락되었습니다: {', '.join(missing_fields)}",
                "필수 컬럼: date,type,category,amount,memo,tags"
            )

    def _csv_row_to_transaction(self, row: Dict[str, str], row_number: int) -> Transaction:
        try:
            date = self._validate_csv_date(row.get("date", ""))
            transaction_type = self._validate_csv_type(row.get("type", ""))
            category_name = self._validate_csv_category(row.get("category", ""))
            amount = self._validate_csv_amount(row.get("amount", ""))
        except BudgetAppError as e:
            raise BudgetAppError(
                f"CSV {row_number}번째 줄이 올바르지 않습니다: {e.message}",
                e.hint
            )

        memo = row.get("memo", "").strip() or None
        raw_tags = row.get("tags", "")
        tags = [
            tag.strip()
            for tag in raw_tags.split(",")
            if tag.strip()
        ]

        return Transaction(
            type=transaction_type,
            date=date,
            amount=amount,
            category=Category(name=category_name),
            memo=memo,
            tags=tags
        )

    def _transaction_to_csv_row(self, transaction: Transaction) -> Dict[str, Any]:
        return {
            "date": transaction.date.strftime("%Y-%m-%d"),
            "type": transaction.type,
            "category": transaction.category.name,
            "amount": transaction.amount,
            "memo": transaction.memo or "",
            "tags": ",".join(transaction.tags or []),
        }

    def _validate_csv_date(self, value: str) -> str:
        cleaned_value = value.strip()
        try:
            datetime.strptime(cleaned_value, "%Y-%m-%d")
        except ValueError:
            raise BudgetAppError(
                "날짜 형식이 올바르지 않습니다.",
                "YYYY-MM-DD 형식으로 입력해주세요."
            )
        return cleaned_value

    def _validate_csv_type(self, value: str) -> str:
        cleaned_value = value.strip().lower()
        if cleaned_value not in ("income", "expense"):
            raise BudgetAppError(
                "타입이 올바르지 않습니다.",
                "income 또는 expense 중 하나를 입력해주세요."
            )
        return cleaned_value

    def _validate_csv_category(self, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise BudgetAppError(
                "카테고리 이름이 올바르지 않습니다.",
                "공백이 아닌 카테고리를 입력해주세요."
            )
        if not self.category_service.exists_category(cleaned_value):
            raise BudgetAppError(
                f"카테고리 '{cleaned_value}'이(가) 존재하지 않습니다.",
                "CSV를 가져오기 전에 해당 카테고리를 먼저 추가하세요."
            )
        return cleaned_value

    def _validate_csv_amount(self, value: str) -> int:
        try:
            amount = int(value.strip())
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


    def list_transactions(self, limit: Optional[int] = None) -> Generator[Transaction, None, None]:
        max_count = limit if limit is not None else 10
        if max_count <= 0:
            return

        count = 0
        for index_entry in self.storage.load_transaction_date_index_stream():
            yield self.storage.read_transaction_at_offset(index_entry["offset"])
            count += 1
            if count >= max_count:
                break


    def search_transactions(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        category: Optional[str] = None,
        _type: Optional[str] = None,
        q: Optional[str] = None,
        tag: Optional[str] = None
    ) -> Generator[Transaction, None, None]:
        for index_entry in self.storage.load_transaction_date_index_stream():
            indexed_date = index_entry["date"]
            if to_date and indexed_date > to_date:
                continue
            if from_date and indexed_date < from_date:
                break

            transaction = self.storage.read_transaction_at_offset(index_entry["offset"])
            if category and transaction.category.name != category:
                continue
            if _type and transaction.type != _type:
                continue
            if q and q not in (transaction.memo or ""):
                continue
            if tag and tag not in (transaction.tags or []):
                continue

            yield transaction

    def summarize_month(self, month: str, top: int = 5) -> Dict[str, Any]:
        month_start = f"{month}-01"
        next_month_start = self._next_month_start(month)
        total_income = 0
        total_expense = 0
        transaction_count = 0
        category_expenses: Dict[str, int] = {}

        for index_entry in self.storage.load_transaction_date_index_stream():
            indexed_date = index_entry["date"]
            if indexed_date >= next_month_start:
                continue
            if indexed_date < month_start:
                break

            transaction = self.storage.read_transaction_at_offset(index_entry["offset"])
            transaction_count += 1
            if transaction.type == "income":
                total_income += transaction.amount
            elif transaction.type == "expense":
                total_expense += transaction.amount
                category_name = transaction.category.name
                category_expenses[category_name] = (
                    category_expenses.get(category_name, 0) + transaction.amount
                )

        top_categories = sorted(
            category_expenses.items(),
            key=lambda item: item[1],
            reverse=True
        )[:top]

        return {
            "month": month,
            "has_data": transaction_count > 0,
            "total_income": total_income,
            "total_expense": total_expense,
            "balance": total_income - total_expense,
            "top_categories": top_categories,
        }

    def _next_month_start(self, month: str) -> str:
        month_date = datetime.strptime(month, "%Y-%m")
        year = month_date.year
        month_number = month_date.month
        if month_number == 12:
            return f"{year + 1}-01-01"
        return f"{year}-{month_number + 1:02d}-01"



            
    

    
