import sys
from typing import NoReturn

class BudgetAppError(Exception):
    def __init__(self, message: str, hint: str = ""):
        self.message = message
        self.hint = hint
        super().__init__(self.message)

def handle_error_and_exit(error: BudgetAppError) -> NoReturn:
    print(f"[오류] {error.message}")
    if error.hint:
        print(f"[힌트] {error.hint}")
    sys.exit(1)