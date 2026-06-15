import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, date
from typing import List, Optional, Dict, Any, Literal

@dataclass
class Category:
    name: str

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("카테고리 이름은 비어있을 수 없습니다.")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Category":
        return cls(name=data["name"])


@dataclass
class Budget:
    month: str
    amount: int

    def __post_init__(self) -> None:
        if not self.month or not self.month.strip():
            raise ValueError("month는 비어있을 수 없습니다.")
        if self.amount <= 0:
            raise ValueError("amount must be positive")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Budget":
        return cls(month=data["month"], amount=data["amount"])


@dataclass
class Transaction:
    type: Literal["income", "expense"]  
    date: date
    amount: int
    category: Category
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    memo: Optional[str] = None
    tags: Optional[List[str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.type not in ("income", "expense"):
            raise ValueError("type must be 'income' or 'expense'")
        if self.amount < 0:
            raise ValueError("amount must be non-negative")
        if isinstance(self.date, str):
            try:
                self.date = datetime.strptime(self.date, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("Invalid date format. Please use YYYY-MM-DD.")
        if isinstance(self.category, dict):
            self.category = Category.from_dict(self.category)
        
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "date": self.date.strftime("%Y-%m-%d") if isinstance(self.date, date) else self.date,
            "amount": self.amount,
            "category": self.category.to_dict(),
            "memo": self.memo,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Transaction":
        return cls(
            id=data["id"],
            type=data["type"],
            date=data["date"],
            amount=data["amount"],
            category=data["category"],
            memo=data.get("memo"),
            tags=data.get("tags"),
        )
