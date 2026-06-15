from budget_app.storage import Storage
from budget_app.services import BudgetService
from budget_app.services import CategoryService
from budget_app.services import TransactionService
from budget_app.cli import CLI


def main() -> None:
    storage = Storage(data_dir="./data")
    category_service = CategoryService(storage=storage)
    budget_service = BudgetService(storage=storage)
    transaction_service = TransactionService(storage=storage, category_service=category_service)
    cli = CLI(
        category_service=category_service, 
        transaction_service=transaction_service,
        budget_service=budget_service
        )
    cli.execute()


if __name__ == "__main__":
    main()
