import json
from pathlib import Path
from typing import Generator, Dict, Any, Iterable, List
from budget_app.models import Budget, Category, Transaction

class Storage:
    def __init__(self, data_dir: str = "./data") -> None:
        """저장소가 사용할 파일 경로를 준비하고, 필요한 파일을 초기화한다."""
        self.data_dir = Path(data_dir)
        self.categories_file = self.data_dir / "categories.jsonl"
        self.budgets_file = self.data_dir / "budgets.jsonl"
        self.transactions_file = self.data_dir / "transactions.jsonl"
        self.transaction_date_index_file = self.data_dir / "transactions_date.index.json"
        self.initialize_storage()

    def initialize_storage(self) -> None:
        """data 디렉터리와 영속성 파일들이 없으면 생성한다."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.categories_file.exists():
            self.categories_file.touch()
        if not self.budgets_file.exists():
            self.budgets_file.touch()
        if not self.transactions_file.exists():
            self.transactions_file.touch()
        if not self.transaction_date_index_file.exists():
            self.transaction_date_index_file.touch()

    def load_categories_stream(self) -> Generator[Category, None, None]:
        """카테고리 파일을 한 줄씩 읽어 Category 객체로 yield한다."""
        if not self.categories_file.exists():
            return
        with open(self.categories_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                # JSONL 한 줄을 Category 도메인 객체로 복원한다.
                yield Category.from_dict(json.loads(line))

    def append_category(self, category: Category) -> None:
        """새 카테고리를 categories.jsonl 끝에 append한다."""
        with open(self.categories_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(category.to_dict(), ensure_ascii=False) + "\n")

    def load_budgets_stream(self) -> Generator[Budget, None, None]:
        """예산 파일을 한 줄씩 읽어 Budget 객체로 yield한다."""
        if not self.budgets_file.exists():
            return
        with open(self.budgets_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                # JSONL 한 줄을 Budget 도메인 객체로 복원한다.
                yield Budget.from_dict(json.loads(line))

    def get_budget(self, month: str) -> Budget | None:
        """month에 해당하는 예산을 찾고, 없으면 None을 반환한다."""
        for budget in self.load_budgets_stream():
            if budget.month == month:
                return budget
        return None

    def set_budget(self, budget: Budget) -> Budget:
        """월 예산을 저장한다. 같은 month가 있으면 교체하고 파일을 원자적으로 재작성한다."""
        # 같은 month의 기존 예산을 제거해서 중복 저장을 막는다.
        budgets = [
            existing
            for existing in self.load_budgets_stream()
            if existing.month != budget.month
        ]
        budgets.append(budget)
        # 사람이 파일을 봤을 때도 예측 가능한 순서가 되도록 month 기준 정렬한다.
        budgets.sort(key=lambda existing: existing.month)

        temp_file = self.budgets_file.with_suffix(".jsonl.tmp")
        try:
            # 임시 파일에 전체 예산을 먼저 쓴 뒤 replace로 교체한다.
            with open(temp_file, "w", encoding="utf-8") as f:
                for existing in budgets:
                    f.write(json.dumps(existing.to_dict(), ensure_ascii=False) + "\n")
            temp_file.replace(self.budgets_file)
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e
        return budget

    def overwrite_categories(self, categories: List[Category]) -> None:
        """카테고리 목록을 임시 파일에 전체 재작성한 뒤 원본 파일과 교체한다."""
        temp_file = self.categories_file.with_suffix(".jsonl.tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                for cat in categories:
                    f.write(json.dumps(cat.to_dict(), ensure_ascii=False) + "\n")
            temp_file.replace(self.categories_file)
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e

    def is_category_used_in_transactions(self, category_name: str) -> bool:
        """거래 파일을 스트리밍으로 확인해 특정 카테고리가 사용 중인지 검사한다."""
        if not self.transactions_file.exists():
            return False
        with open(self.transactions_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                tx_data = json.loads(line)
                # Transaction 객체를 만들지 않고 JSON dict에서 category.name만 확인한다.
                if tx_data.get("category", {}).get("name") == category_name:
                    return True
        return False

    def append_transaction(self, transaction: Transaction) -> int:
        """거래를 transactions.jsonl 끝에 append하고, 새 줄의 byte offset을 반환한다."""
        with open(self.transactions_file, "ab") as f:
            # append binary 모드에서는 쓰기 위치가 파일 끝이다.
            # 이 값은 새 transaction JSON 라인이 시작되는 byte 위치다.
            offset = f.tell()
            line = json.dumps(transaction.to_dict(), ensure_ascii=False) + "\n"
            # offset은 byte 기준이므로 UTF-8 bytes로 직접 기록한다.
            f.write(line.encode("utf-8"))
        return offset

    def append_transaction_date_index(self, transaction: Transaction, offset: int) -> None:
        """새 거래의 date index entry를 B+tree 유사 JSON index에 삽입한다."""
        # index entry는 date 최신순 정렬 key와 원본 파일 seek용 offset을 가진다.
        index_entry = {
            "date": transaction.date.strftime("%Y-%m-%d"),
            "id": transaction.id,
            "offset": offset,
        }
        order = 4
        # 기존 index root를 읽고, 새 entry를 leaf까지 내려가 삽입한다.
        root = self._load_transaction_date_index_root()
        split_node = self._insert_transaction_date_index_entry(root, index_entry, order)
        if split_node:
            # root가 split되면 새 internal root를 만든다.
            root = {
                "leaf": False,
                "keys": [],
                "children": [root, split_node],
            }
            self._refresh_transaction_date_index_keys(root)

        index_data = {
            "type": "transaction_date_btree_index",
            "sort": "date_desc_id_desc",
            "order": order,
            "root": root,
        }

        temp_file = self.transaction_date_index_file.with_suffix(".json.tmp")
        try:
            # index 파일도 임시 파일에 먼저 쓴 뒤 replace로 교체한다.
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            temp_file.replace(self.transaction_date_index_file)
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e

    def overwrite_transactions(self, transactions: Iterable[Transaction]) -> None:
        """거래 전체를 재작성하고, 새 offset 기준으로 date index도 재생성한다."""
        temp_transactions_file = self.transactions_file.with_suffix(".jsonl.tmp")
        temp_index_file = self.transaction_date_index_file.with_suffix(".json.tmp")
        index_entries: List[Dict[str, Any]] = []

        try:
            with open(temp_transactions_file, "wb") as f:
                for transaction in transactions:
                    # 전체 재작성 시 각 줄의 offset이 바뀔 수 있으므로 다시 계산한다.
                    offset = f.tell()
                    line = json.dumps(transaction.to_dict(), ensure_ascii=False) + "\n"
                    f.write(line.encode("utf-8"))
                    # 새 offset을 기준으로 index entry를 다시 만든다.
                    index_entries.append({
                        "date": transaction.date.strftime("%Y-%m-%d"),
                        "id": transaction.id,
                        "offset": offset,
                    })

            # 모은 index entry를 B+tree 유사 구조로 다시 구성한다.
            index_data = {
                "type": "transaction_date_btree_index",
                "sort": "date_desc_id_desc",
                "order": 4,
                "root": self._build_transaction_date_index_by_insert(index_entries, order=4),
            }
            with open(temp_index_file, "w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
                f.write("\n")

            # 두 temp 파일이 모두 성공적으로 만들어진 뒤 원본을 교체한다.
            temp_transactions_file.replace(self.transactions_file)
            temp_index_file.replace(self.transaction_date_index_file)
        except Exception as e:
            if temp_transactions_file.exists():
                temp_transactions_file.unlink()
            if temp_index_file.exists():
                temp_index_file.unlink()
            raise e

    def _load_transaction_date_index_root(self) -> Dict[str, Any]:
        """date index 파일에서 root node를 읽는다. 비어 있으면 빈 leaf root를 반환한다."""
        empty_root = {
            "leaf": True,
            "keys": [],
            "entries": [],
        }
        if not self.transaction_date_index_file.exists():
            return empty_root

        raw_index = self.transaction_date_index_file.read_text(encoding="utf-8").strip()
        if not raw_index:
            return empty_root

        try:
            index_data = json.loads(raw_index)
        except json.JSONDecodeError:
            # 과거 JSONL index 형식이 남아 있으면 한 줄씩 읽어 새 tree로 복원한다.
            root = empty_root
            for line in raw_index.splitlines():
                if not line.strip():
                    continue
                self._insert_transaction_date_index_entry(root, json.loads(line), order=4) 
            return root

        if isinstance(index_data, dict) and isinstance(index_data.get("root"), dict):
            # 현재 index 파일 형식: {"root": ...}
            return index_data["root"]

        if isinstance(index_data, list):
            # 과거 list 형식 index를 읽어 tree로 변환한다.
            root = empty_root
            for entry in index_data:
                self._insert_transaction_date_index_entry(root, entry, order=4)
            return root

        return empty_root

    def _load_transaction_date_index_entries(self) -> List[Dict[str, Any]]:
        """index tree 전체를 펼쳐서 leaf entry 목록으로 반환한다."""
        if not self.transaction_date_index_file.exists():
            return []

        raw_index = self.transaction_date_index_file.read_text(encoding="utf-8").strip()
        if not raw_index:
            return []

        try:
            index_data = json.loads(raw_index)
        except json.JSONDecodeError:
            return [
                json.loads(line)
                for line in raw_index.splitlines()
                if line.strip()
            ]

        if isinstance(index_data, list):
            return index_data

        if isinstance(index_data, dict):
            return self._collect_transaction_date_index_entries(index_data.get("root", {}))

        return []

    def _collect_transaction_date_index_entries(self, node: Dict[str, Any]) -> List[Dict[str, Any]]:
        """index node를 재귀 순회해 leaf에 있는 entry만 수집한다."""
        if not node:
            return []
        if node.get("leaf"):
            return list(node.get("entries", []))

        entries: List[Dict[str, Any]] = []
        for child in node.get("children", []):
            entries.extend(self._collect_transaction_date_index_entries(child))
        return entries

    def _build_transaction_date_btree(
        self,
        entries: List[Dict[str, Any]],
        order: int
    ) -> Dict[str, Any]:
        """정렬된 entry 목록을 leaf 묶음으로 나눠 B+tree 유사 구조를 만든다."""
        if not entries:
            return {
                "leaf": True,
                "keys": [],
                "entries": [],
            }

        # order 개수만큼 entry를 잘라 leaf node들을 만든다.
        leaves = [
            {
                "leaf": True,
                "keys": [self._transaction_date_index_key(entry) for entry in entries[i:i + order]],
                "entries": entries[i:i + order],
            }
            for i in range(0, len(entries), order)
        ]

        # leaf들이 한 root에 담길 때까지 상위 internal level을 반복 생성한다.
        level = leaves
        while len(level) > 1:
            level = [
                {
                    "leaf": False,
                    "keys": [child["keys"][0] for child in level[i:i + order] if child["keys"]],
                    "children": level[i:i + order],
                }
                for i in range(0, len(level), order)
            ]

        return level[0]

    def _transaction_date_index_key(self, entry: Dict[str, Any]) -> str:
        """date index 정렬 key를 만든다. YYYY-MM-DD#id는 문자열 비교로 날짜순 정렬이 가능하다."""
        return f'{entry["date"]}#{entry["id"]}'

    def _build_transaction_date_index_by_insert(
        self,
        entries: Iterable[Dict[str, Any]],
        order: int
    ) -> Dict[str, Any]:
        """entry들을 하나씩 삽입해 node split 방식으로 index tree를 만든다."""
        root = {
            "leaf": True,
            "keys": [],
            "entries": [],
        }
        for entry in entries:
            # root부터 적절한 leaf까지 내려가 entry를 삽입한다.
            split_node = self._insert_transaction_date_index_entry(root, entry, order)
            if split_node:
                # root split이 발생하면 새 root를 만든다.
                root = {
                    "leaf": False,
                    "keys": [],
                    "children": [root, split_node],
                }
                self._refresh_transaction_date_index_keys(root)
        return root

    def _insert_transaction_date_index_entry(
        self,
        node: Dict[str, Any],
        entry: Dict[str, Any],
        order: int
    ) -> Dict[str, Any] | None:
        """index tree에 entry를 삽입하고, split이 발생하면 오른쪽 node를 반환한다."""
        if node.get("leaf"):
            # 같은 id가 이미 있으면 제거한 뒤 새 entry로 교체한다.
            entries = [
                existing
                for existing in node.get("entries", [])
                if existing["id"] != entry["id"]
            ]
            entries.append(entry)
            # date desc, id desc 기준으로 leaf 내부 순서를 유지한다.
            entries.sort(key=self._transaction_date_index_key, reverse=True)
            node["entries"] = entries
            self._refresh_transaction_date_index_keys(node)

            if len(node["entries"]) > order:
                # leaf가 order를 초과하면 split해서 오른쪽 node를 부모로 올린다.
                return self._split_transaction_date_index_node(node)
            return None

        # internal node에서는 key 기준으로 내려갈 child를 찾는다.
        child_index = self._find_transaction_date_index_child(
            node,
            self._transaction_date_index_key(entry)
        )
        split_node = self._insert_transaction_date_index_entry(
            node["children"][child_index],
            entry,
            order
        )
        if split_node:
            # child split 결과를 현재 internal node의 children에 삽입한다.
            node["children"].insert(child_index + 1, split_node)

        self._refresh_transaction_date_index_keys(node)
        if len(node["children"]) > order:
            # internal node도 order를 초과하면 split 결과를 부모로 올린다.
            return self._split_transaction_date_index_node(node)
        return None

    def _find_transaction_date_index_child(self, node: Dict[str, Any], key: str) -> int:
        """내림차순 key 배열에서 삽입할 entry가 내려갈 child index를 찾는다."""
        keys = node.get("keys", [])
        child_index = 0
        # keys는 각 child의 대표 key다. key가 다음 대표 key보다 작거나 같으면 더 뒤 child로 이동한다.
        while child_index + 1 < len(keys) and key <= keys[child_index + 1]:
            child_index += 1
        return child_index

    def _split_transaction_date_index_node(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """order를 초과한 node를 왼쪽은 기존 node에 남기고, 오른쪽 node를 새로 만들어 반환한다."""
        if node.get("leaf"):
            entries = node["entries"]
            # 왼쪽 node가 하나 더 많이 갖도록 중간 지점을 잡는다.
            split_at = (len(entries) + 1) // 2
            right_entries = entries[split_at:]
            node["entries"] = entries[:split_at]
            self._refresh_transaction_date_index_keys(node)

            right_node = {
                "leaf": True,
                "keys": [],
                "entries": right_entries,
            }
            self._refresh_transaction_date_index_keys(right_node)
            return right_node

        children = node["children"]
        # internal node는 children 목록을 반으로 나눠 오른쪽 internal node를 만든다.
        split_at = (len(children) + 1) // 2
        right_children = children[split_at:]
        node["children"] = children[:split_at]
        self._refresh_transaction_date_index_keys(node)

        right_node = {
            "leaf": False,
            "keys": [],
            "children": right_children,
        }
        self._refresh_transaction_date_index_keys(right_node)
        return right_node

    def _refresh_transaction_date_index_keys(self, node: Dict[str, Any]) -> None:
        """node의 keys 배열을 현재 entries/children 상태에 맞게 다시 계산한다."""
        if node.get("leaf"):
            # leaf key는 각 entry의 date#id다.
            node["keys"] = [
                self._transaction_date_index_key(entry)
                for entry in node.get("entries", [])
            ]
            return

        # internal key는 각 child의 첫 번째 대표 key다.
        node["keys"] = [
            child["keys"][0]
            for child in node.get("children", [])
            if child.get("keys")
        ]

    def load_transaction_date_index_stream(self) -> Generator[Dict[str, Any], None, None]:
        """date index를 최신순으로 순회하며 leaf entry를 yield한다."""
        root = self._load_transaction_date_index_root()
        yield from self._walk_transaction_date_index(root)

    def _walk_transaction_date_index(
        self,
        node: Dict[str, Any]
    ) -> Generator[Dict[str, Any], None, None]:
        """index tree를 재귀적으로 순회해 leaf entry를 순서대로 yield한다."""
        if not node:
            return
        if node.get("leaf"):
            # 실제 index entry는 leaf node에만 있다.
            for entry in node.get("entries", []):
                yield entry
            return

        # children은 최신순으로 정렬된 상태이므로 앞 child부터 순회한다.
        for child in node.get("children", []):
            yield from self._walk_transaction_date_index(child)

    def read_transaction_at_offset(self, offset: int) -> Transaction:
        """transactions.jsonl에서 byte offset으로 이동해 해당 거래 한 줄만 읽는다."""
        with open(self.transactions_file, "rb") as f:
            f.seek(offset)
            line = f.readline().decode("utf-8")
        return Transaction.from_dict(json.loads(line))
    
    def load_transactions_stream(self) -> Generator[Transaction, None, None]:
        """거래 파일을 처음부터 한 줄씩 읽어 Transaction 객체로 yield한다."""
        if not self.transactions_file.exists():
            return
        with open(self.transactions_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                # JSONL 한 줄을 Transaction 도메인 객체로 복원한다.
                yield Transaction.from_dict(json.loads(line))
