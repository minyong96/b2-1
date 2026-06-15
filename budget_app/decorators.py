from functools import wraps
import sys
from time import perf_counter
from typing import Callable, ParamSpec, TypeVar
from budget_app.errors import BudgetAppError, handle_error_and_exit

P = ParamSpec("P") # 함수의 매개변수 타입을 캡처하기 위한 제네릭 타입 변수 

R = TypeVar("R") # 함수의 반환 타입을 캡처하기 위한 제네릭 타입 변수

def exception_handler(func: Callable[P, R]) -> Callable[P, R]: 
    @wraps(func) # 함수의 메타데이터(이름, docstring 등)를 유지하기 위한 데코레이터
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except BudgetAppError as e:
            handle_error_and_exit(e)
        except Exception as e:
            handle_error_and_exit(BudgetAppError(f"시스템 오류가 발생했습니다: {str(e)}"))
    return wrapper

def execution_logger(func: Callable[P, R]) -> Callable[P, R]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        command = " ".join(sys.argv[1:]) or "help"
        print(f"[로그] command 시작: {command}", file=sys.stderr)
        try:
            result = func(*args, **kwargs)
        except Exception:
            print(f"[로그] command 실패: {command}", file=sys.stderr)
            raise
        print(f"[로그] command 종료: {command}", file=sys.stderr)
        return result
    return wrapper

def execution_timer(func: Callable[P, R]) -> Callable[P, R]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        started_at = perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed_ms = (perf_counter() - started_at) * 1000
            print(f"[시간] {func.__name__}: {elapsed_ms:.2f}ms", file=sys.stderr)
    return wrapper
