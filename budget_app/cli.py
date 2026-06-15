import sys
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from budget_app.errors import BudgetAppError
from budget_app.services import BudgetService, CategoryService, TransactionService
from budget_app.validators import Validator
from budget_app.decorators import exception_handler, execution_logger, execution_timer

class CLI:
    def __init__(
        self,
        category_service: CategoryService,
        transaction_service: TransactionService,
        budget_service: BudgetService
    ) -> None:
        self.category_service = category_service
        self.transaction_service = transaction_service
        self.budget_service = budget_service

    @exception_handler
    @execution_logger
    @execution_timer
    def execute(self) -> None:
        if len(sys.argv) < 2:
            self.print_main_help()
            return

        main_command = sys.argv[1]

        # 1. 카테고리 도메인 명령어 분기
        if main_command == "category":
            if len(sys.argv) < 3:
                self.print_category_help()
                return
            
            subcommand = sys.argv[2]
            if subcommand == "add":
                self.handle_category_add()
            elif subcommand == "list":
                self.handle_category_list()
            elif subcommand == "remove":
                self.handle_category_remove()
            else:
                raise BudgetAppError(
                    f"알 수 없는 카테고리 명령입니다: {subcommand}",
                    "Usage: python -m budget_app category [add|list|remove]"
                )

        # 2. 트랜잭션 도메인 명령어 분기
        elif main_command == "add":
            self.handle_transaction_add()
            
        elif main_command == "list":
            self.handle_transaction_list()
            
        elif main_command == "search":
            self.handle_transaction_search()

        elif main_command == "delete":
            self.handle_transaction_delete()

        elif main_command == "update":
            self.handle_transaction_update()

        elif main_command == "summary":
            self.handle_transaction_summary()

        elif main_command == "budget":
            if len(sys.argv) < 3:
                self.print_budget_help()
                return

            subcommand = sys.argv[2]
            if subcommand == "set":
                self.handle_budget_set()
            else:
                raise BudgetAppError(
                    f"알 수 없는 예산 명령입니다: {subcommand}",
                    "Usage: python -m budget_app budget set --month YYYY-MM --amount N"
                )

        elif main_command == "import":
            self.handle_transaction_import()

        elif main_command == "export":
            self.handle_transaction_export()
            
        else:
            raise BudgetAppError(
                f"알 수 없는 명령어입니다: {main_command}",
                "Usage: python -m budget_app <command> [options]"
            )

    # =========================================================================
    # [Category 도메인 핸들러]
    # =========================================================================
    def handle_category_add(self) -> None:
        raw_name = input("카테고리명: ")
        validated_name = Validator.validate_category_name(raw_name)
        cat = self.category_service.add_category(validated_name)
        print(f"[저장 완료] category={cat.name}")

    def handle_category_list(self) -> None:
        categories = self.category_service.list_categories()
        if not categories:
            print("등록된 카테고리가 없습니다.")
            return
        for cat in categories:
            print(f"- {cat.name}")

    def handle_category_remove(self) -> None:
        raw_name = input("삭제할 카테고리명: ")
        validated_name = Validator.validate_category_name(raw_name)
        self.category_service.remove_category(validated_name)
        print(f"[삭제 완료] category={validated_name}")

    # =========================================================================
    # [Transaction 도메인 핸들러]
    # =========================================================================
    def handle_transaction_add(self) -> None:
        """거래 추가 (요구사항: 대화형 입력 방식 필수)"""
        print("=== 새로운 거래 내역 추가 ===")
        raw_date = input("날짜(YYYY-MM-DD): ")
        raw_type = input("타입(income/expense): ")
        raw_category = input("카테고리: ")
        raw_amount = input("금액(양수): ")
        raw_memo = input("메모(선택, 없으면 엔터): ")
        raw_tags = input("태그(쉼표로 구분, 없으면 엔터): ")

        # 밸리데이터를 통한 값 사전 검증 (정수 변환 등)
        validated_date = Validator.validate_date(raw_date)
        validated_type = Validator.validate_type(raw_type)
        validated_category = Validator.validate_category_name(raw_category)
        validated_amount = Validator.validate_amount(raw_amount)
        
        # 서비스 레이어 호출 및 데이터 영속화
        tx = self.transaction_service.add_transaction(
            amount=validated_amount,
            category_name=validated_category,
            type=validated_type,
            date=validated_date,
            memo=raw_memo.strip() if raw_memo.strip() else None,
            tags=raw_tags.strip() if raw_tags.strip() else None
        )
        print(f"[저장 완료] id={tx.id}")

    def handle_transaction_list(self) -> None:
        """거래 목록 조회 (요구사항: --limit N 옵션 지원 및 기본값 제공)"""
        options = self._parse_custom_options()
        
        # --limit 값 추출 (기본값 10 설정)
        limit_val = 10
        if "--limit" in options and options["--limit"]:
            try:
                limit_val = int(options["--limit"])
                if limit_val <= 0:
                    raise ValueError
            except ValueError:
                print("[경고] --limit 값은 양의 정수여야 합니다. 기본값(10)으로 대체합니다.")
                limit_val = 10

        # 스트리밍 출력 연동
        print(f"\n[최근 거래 내역 최대 {limit_val}개 출력]")
        tx_stream = self.transaction_service.list_transactions(limit=limit_val)
        
        count = 0
        for tx in tx_stream:
            count += 1
            tags_str = ", ".join(tx.tags) if tx.tags else ""
            print(f"{tx.id} | {tx.date} | {tx.type:<7} | {tx.category.name:<10} | {tx.amount:>7}원 | {tx.memo or ''} | {tags_str}")
        
        if count == 0:
            print("조회된 거래 내역이 없습니다.")

    def handle_transaction_search(self) -> None:
        """거래 검색 (요구사항: --from, --to, --category, --type, --q, --tag 옵션 지원)"""
        options = self._parse_custom_options()
        
        # 옵션 맵에서 검색 파라미터 안전하게 추출
        from_date = options.get("--from")
        to_date = options.get("--to")
        category = options.get("--category")
        _type = options.get("--type")
        q = options.get("--q")
        tag = options.get("--tag")

        # 서비스 레이어에 스트리밍 검색 요청
        search_stream = self.transaction_service.search_transactions(
            from_date=from_date,
            to_date=to_date,
            category=category,
            _type=_type,
            q=q,
            tag=tag
        )

        print("\n[검색 결과 출력 (최신순)]")
        count = 0
        for tx in search_stream:
            count += 1
            tags_str = ", ".join(tx.tags) if tx.tags else ""
            print(f"{tx.id} | {tx.date} | {tx.type:<7} | {tx.category.name:<10} | {tx.amount:>7}원 | {tx.memo or ''} | {tags_str}")
        
        if count == 0:
            print("조건에 부합하는 거래 내역이 없습니다.")

    def handle_transaction_delete(self) -> None:
        options = self._parse_custom_options()
        transaction_id = options.get("--id")
        if not transaction_id:
            raise BudgetAppError(
                "삭제할 거래 id를 입력해주세요.",
                "예: delete --id <id>"
            )

        deleted = self.transaction_service.delete_transaction(transaction_id)
        if not deleted:
            print(f"[안내] id={transaction_id} 거래는 없는 데이터입니다.")
            return
        print(f"[삭제 완료] id={transaction_id}")

    def handle_transaction_update(self) -> None:
        options = self._parse_custom_options()
        transaction_id = options.get("--id")
        if not transaction_id:
            raise BudgetAppError(
                "수정할 거래 id를 입력해주세요.",
                "예: update --id <id> [options]"
            )

        date = Validator.validate_date(options["--date"]) if options.get("--date") else None
        _type = Validator.validate_type(options["--type"]) if options.get("--type") else None
        category = (
            Validator.validate_category_name(options["--category"])
            if options.get("--category")
            else None
        )
        amount = Validator.validate_amount(options["--amount"]) if options.get("--amount") else None
        memo = options.get("--memo")
        tags = options.get("--tags")

        tx = self.transaction_service.update_transaction(
            transaction_id=transaction_id,
            date=date,
            type=_type,
            category_name=category,
            amount=amount,
            memo=memo,
            tags=tags
        )
        if tx is None:
            print(f"[안내] id={transaction_id} 거래는 없는 데이터입니다.")
            return
        print(f"[수정 완료] id={tx.id}")

    def handle_transaction_summary(self) -> None:
        options = self._parse_custom_options()
        if not options.get("--month"):
            raise BudgetAppError(
                "요약할 월을 입력해주세요.",
                "예: summary --month 2026-06"
            )

        month = Validator.validate_month(options["--month"])
        top = 5
        if options.get("--top"):
            try:
                top = int(options["--top"])
                if top <= 0:
                    raise ValueError
            except ValueError:
                print("[경고] --top 값은 양의 정수여야 합니다. 기본값(5)으로 대체합니다.")
                top = 5

        summary = self.transaction_service.summarize_month(month=month, top=top)
        budget = self.budget_service.get_budget(month)
        print(f"\n[월별 요약] {month}")
        if not summary["has_data"]:
            print("데이터 없음")
            self._print_budget_summary(budget, summary["total_expense"])
            return

        print(f"총 수입: {summary['total_income']}원")
        print(f"총 지출: {summary['total_expense']}원")
        print(f"잔액: {summary['balance']}원")
        self._print_budget_summary(budget, summary["total_expense"])
        print(f"\n[카테고리별 지출 TOP {top}]")
        if not summary["top_categories"]:
            print("지출 데이터 없음")
            return

        for rank, (category_name, amount) in enumerate(summary["top_categories"], start=1):
            print(f"{rank}. {category_name} | {amount}원")

    def handle_budget_set(self) -> None:
        options = self._parse_custom_options()
        if not options.get("--month"):
            raise BudgetAppError(
                "예산을 설정할 월을 입력해주세요.",
                "예: budget set --month 2026-06 --amount 500000"
            )
        if not options.get("--amount"):
            raise BudgetAppError(
                "예산 금액을 입력해주세요.",
                "예: budget set --month 2026-06 --amount 500000"
            )

        month = Validator.validate_month(options["--month"])
        amount = Validator.validate_amount(options["--amount"])
        budget = self.budget_service.set_budget(month=month, amount=amount)
        print(f"[예산 저장 완료] month={budget.month} amount={budget.amount}원")

    def handle_transaction_import(self) -> None:
        options = self._parse_custom_options()
        csv_path = options.get("--from")
        if not csv_path:
            raise BudgetAppError(
                "가져올 CSV 파일을 입력해주세요.",
                "예: import --from ./transactions.csv"
            )

        count = self.transaction_service.import_transactions_from_csv(csv_path)
        print(f"[가져오기 완료] {count}건 등록")

    def handle_transaction_export(self) -> None:
        options = self._parse_custom_options()
        out_path = options.get("--out")
        if not out_path:
            raise BudgetAppError(
                "저장할 CSV 파일을 입력해주세요.",
                "예: export --out ./transactions.csv --month 2026-06"
            )

        has_month = bool(options.get("--month"))
        has_date_range = bool(options.get("--from") or options.get("--to"))
        if not has_month and not has_date_range:
            raise BudgetAppError(
                "export는 --month 또는 --from/--to 조건이 필요합니다.",
                "예: export --out ./transactions.csv --month 2026-06"
            )
        if has_month and has_date_range:
            raise BudgetAppError(
                "--month와 --from/--to는 동시에 사용할 수 없습니다.",
                "--month 또는 --from/--to 중 하나의 조건만 사용해주세요."
            )

        if has_month:
            month = Validator.validate_month(options["--month"])
            from_date = f"{month}-01"
            to_date = self._last_day_of_month(month)
        else:
            from_date = (
                Validator.validate_date(options["--from"])
                if options.get("--from")
                else None
            )
            to_date = (
                Validator.validate_date(options["--to"])
                if options.get("--to")
                else None
            )
            if from_date and to_date and from_date > to_date:
                raise BudgetAppError(
                    "--from은 --to보다 늦을 수 없습니다.",
                    "시작일과 종료일을 다시 확인해주세요."
                )

        count = self.transaction_service.export_transactions_to_csv(
            out_path=out_path,
            from_date=from_date,
            to_date=to_date
        )
        print(f"[내보내기 완료] {count}건 저장 path={out_path}")

    def _print_budget_summary(self, budget: Any, total_expense: int) -> None:
        if budget is None:
            return

        usage_rate = total_expense / budget.amount * 100
        print(f"예산: {budget.amount}원")
        print(f"예산 사용률: {usage_rate:.1f}%")
        if total_expense > budget.amount:
            print("[경고] 예산을 초과했습니다.")

    def _last_day_of_month(self, month: str) -> str:
        year = int(month[:4])
        month_number = int(month[5:7])
        if month_number == 12:
            return f"{year}-12-31"

        next_month = month_number + 1
        next_month_start = f"{year}-{next_month:02d}-01"
        last_day = datetime.strptime(next_month_start, "%Y-%m-%d") - timedelta(days=1)
        return last_day.strftime("%Y-%m-%d")

    # =========================================================================
    # [내부 유틸리티 메서드]
    # =========================================================================
    def _parse_custom_options(self) -> Dict[str, Optional[str]]:
        """
        sys.argv에서 --option value 형태의 리눅스 표준 인자들을 딕셔너리로 파싱합니다.
        예: --limit 5 -> {"--limit": "5"}
        """
        options: Dict[str, Optional[str]] = {}
        args = sys.argv[2:]  # main_command 이후의 인자들만 대상
        
        i = 0
        while i < len(args):
            if args[i].startswith("--"):
                option_name = args[i]
                # 다음 인자가 있고 다른 옵션(--)이 아니라면 값으로 바인딩
                if i + 1 < len(args) and not args[i+1].startswith("--"):
                    options[option_name] = args[i+1]
                    i += 2
                else:
                    options[option_name] = None
                    i += 1
            else:
                i += 1
        return options

    def print_main_help(self) -> None:
        print("=== 가계부 서비스 도움말 ===")
        print("Usage: python -m budget_app <command> [options]")
        print("\n[지원 명령어]")
        print("  add                         : 새로운 수입/지출 내역을 추가합니다. (대화형)")
        print("  list [--limit N]            : 최근 거래 내역을 최신순 스트리밍 조회합니다.")
        print("  search [options]            : 조건에 맞는 거래 내역을 검색합니다.")
        print("  update --id <id> [options]  : 거래 내역을 옵션 기반으로 수정합니다.")
        print("  delete --id <id>            : 거래 내역을 삭제합니다.")
        print("  summary --month YYYY-MM     : 월별 수입/지출/잔액과 지출 TOP N을 출력합니다.")
        print("  budget set --month YYYY-MM --amount N : 월 예산을 저장합니다.")
        print("  import --from CSV           : CSV 거래 내역을 가져옵니다.")
        print("  export --out CSV [조건]     : 조건에 맞는 거래를 CSV로 저장합니다.")
        print("  category [subcommand]       : 카테고리를 관리합니다. (add/list/remove)")
        print("\n[검색 옵션 예시]")
        print("  python -m budget_app search --from 2026-01-01 --to 2026-01-31")
        print("  python -m budget_app search --category food --type expense --q 점심")
        print("\n[수정 옵션 예시]")
        print("  python -m budget_app update --id <id> --amount 12000 --memo 점심")
        print("\n[요약 옵션 예시]")
        print("  python -m budget_app summary --month 2026-06 --top 3")
        print("\n[예산 옵션 예시]")
        print("  python -m budget_app budget set --month 2026-06 --amount 500000")
        print("\n[가져오기/내보내기 예시]")
        print("  python -m budget_app import --from ./transactions.csv")
        print("  python -m budget_app export --out ./transactions.csv --month 2026-06")

    def print_category_help(self) -> None:
        print("Usage: python -m budget_app category [add|list|remove]")

    def print_budget_help(self) -> None:
        print("Usage: python -m budget_app budget set --month YYYY-MM --amount N")
