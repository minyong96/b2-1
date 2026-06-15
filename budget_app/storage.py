import json
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Optional

from budget_app.models import Budget, Category, Transaction


class Storage:
    INDEX_ORDER = 4

    def __init__(self, data_dir: str = "./data") -> None:
        self.data_dir = Path(data_dir)
        self.categories_file = self.data_dir / "categories.jsonl"
        self.budgets_file = self.data_dir / "budgets.jsonl"
        self.transactions_file = self.data_dir / "transactions.jsonl"
        self.transaction_date_index_file = self.data_dir / "transactions_date.index.json"
        self.initialize_storage()

    def initialize_storage(self) -> None:
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
        if not self.categories_file.exists():
            return
        with open(self.categories_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                yield Category.from_dict(json.loads(line))

    def append_category(self, category: Category) -> None:
        with open(self.categories_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(category.to_dict(), ensure_ascii=False) + "\n")

    def load_budgets_stream(self) -> Generator[Budget, None, None]:
        if not self.budgets_file.exists():
            return
        with open(self.budgets_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                yield Budget.from_dict(json.loads(line))

    def get_budget(self, month: str) -> Budget | None:
        for budget in self.load_budgets_stream():
            if budget.month == month:
                return budget
        return None

    def set_budget(self, budget: Budget) -> Budget:
        budgets = [
            existing
            for existing in self.load_budgets_stream()
            if existing.month != budget.month
        ]
        budgets.append(budget)
        budgets.sort(key=lambda existing: existing.month)

        temp_file = self.budgets_file.with_suffix(".jsonl.tmp")
        try:
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
        if not self.transactions_file.exists():
            return False
        with open(self.transactions_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                tx_data = json.loads(line)
                if tx_data.get("category", {}).get("name") == category_name:
                    return True
        return False

    def append_transaction(self, transaction: Transaction) -> int:
        with open(self.transactions_file, "ab") as f:
            offset = f.tell()
            line = json.dumps(transaction.to_dict(), ensure_ascii=False) + "\n"
            f.write(line.encode("utf-8"))
        return offset

    def append_transaction_date_index(self, transaction: Transaction, offset: int) -> None:
        """
        거래 append 후 date index를 갱신한다.

        지금 구현은 단순화를 위해 기존 index entries를 읽고 전체 B+Tree index를 다시 만든다.
        중요한 점은 range scan 자체는 root seek + leaf linked list(next_leaf_id)를 사용한다는 것이다.
        """
        index_entry = {
            "date": transaction.date.strftime("%Y-%m-%d"),
            "id": transaction.id,
            "offset": offset,
        }

        entries = self._load_transaction_date_index_entries()
        entries = [entry for entry in entries if entry.get("id") != transaction.id]
        entries.append(index_entry)
        index_data = self._build_transaction_date_btree_index(entries, order=self.INDEX_ORDER)
        self._write_transaction_date_index(index_data)

    def overwrite_transactions(self, transactions: Iterable[Transaction]) -> None:
        temp_transactions_file = self.transactions_file.with_suffix(".jsonl.tmp")
        temp_index_file = self.transaction_date_index_file.with_suffix(".json.tmp")
        index_entries: List[Dict[str, Any]] = []

        try:
            with open(temp_transactions_file, "wb") as f:
                for transaction in transactions:
                    offset = f.tell()
                    line = json.dumps(transaction.to_dict(), ensure_ascii=False) + "\n"
                    f.write(line.encode("utf-8"))
                    index_entries.append({
                        "date": transaction.date.strftime("%Y-%m-%d"),
                        "id": transaction.id,
                        "offset": offset,
                    })

            index_data = self._build_transaction_date_btree_index(
                index_entries,
                order=self.INDEX_ORDER,
            )
            with open(temp_index_file, "w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
                f.write("\n")

            temp_transactions_file.replace(self.transactions_file)
            temp_index_file.replace(self.transaction_date_index_file)
        except Exception as e:
            if temp_transactions_file.exists():
                temp_transactions_file.unlink()
            if temp_index_file.exists():
                temp_index_file.unlink()
            raise e

    def _write_transaction_date_index(self, index_data: Dict[str, Any]) -> None:
        temp_file = self.transaction_date_index_file.with_suffix(".json.tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            temp_file.replace(self.transaction_date_index_file)
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e

    def _empty_transaction_date_index(self, order: int | None = None) -> Dict[str, Any]:
        return {
            "type": "transaction_date_btree_index",
            "version": 2,
            "sort": "date_desc_id_desc",
            "order": order or self.INDEX_ORDER,
            "root_id": None,
            "first_leaf_id": None,
            "nodes": {},
        }

    def _load_transaction_date_index(self) -> Dict[str, Any]:
        if not self.transaction_date_index_file.exists():
            return self._empty_transaction_date_index()

        raw_index = self.transaction_date_index_file.read_text(encoding="utf-8").strip()
        if not raw_index:
            return self._empty_transaction_date_index()

        try:
            index_data = json.loads(raw_index)
        except json.JSONDecodeError:
            entries = [
                json.loads(line)
                for line in raw_index.splitlines()
                if line.strip()
            ]
            return self._build_transaction_date_btree_index(entries, order=self.INDEX_ORDER)

        if self._is_linked_btree_index(index_data):
            return index_data

        # 이전 포맷(list 또는 root 중첩 dict)을 읽으면 새 포맷으로 변환해서 반환한다.
        entries = self._collect_entries_from_any_index(index_data)
        return self._build_transaction_date_btree_index(entries, order=self.INDEX_ORDER)

    def _is_linked_btree_index(self, index_data: Any) -> bool:
        return (
            isinstance(index_data, dict)
            and isinstance(index_data.get("nodes"), dict)
            and "root_id" in index_data
        )

    def _collect_entries_from_any_index(self, index_data: Any) -> List[Dict[str, Any]]:
        if isinstance(index_data, list):
            return list(index_data)

        if isinstance(index_data, dict):
            if self._is_linked_btree_index(index_data):
                entries: List[Dict[str, Any]] = []
                leaf_id = index_data.get("first_leaf_id") # None
                nodes = index_data.get("nodes", {})
                while leaf_id:
                    leaf = nodes.get(leaf_id)
                    if not leaf:
                        break
                    entries.extend(leaf.get("entries", []))
                    leaf_id = leaf.get("next_leaf_id") 
                return entries

            if isinstance(index_data.get("root"), dict):
                return self._collect_transaction_date_index_entries_from_nested_node(index_data["root"])

            if index_data.get("leaf") is not None:
                return self._collect_transaction_date_index_entries_from_nested_node(index_data)

        return []

    def _load_transaction_date_index_entries(self) -> List[Dict[str, Any]]:
        index_data = self._load_transaction_date_index()
        return self._collect_entries_from_any_index(index_data)

    def _collect_transaction_date_index_entries_from_nested_node(
        self,
        node: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if not node:
            return []
        if node.get("leaf"):
            return list(node.get("entries", []))

        entries: List[Dict[str, Any]] = []
        for child in node.get("children", []):
            entries.extend(self._collect_transaction_date_index_entries_from_nested_node(child))
        return entries

    def _build_transaction_date_btree_index(
        self,
        entries: Iterable[Dict[str, Any]],
        order: int,
    ) -> Dict[str, Any]:
        """
        B+Tree index를 파일에 저장 가능한 형태로 만든다.

        핵심 구조:
        - root_id: 탐색 시작 노드 id
        - nodes: node_id -> node dict
        - leaf.next_leaf_id: 다음 leaf의 id

        즉, next에 dict를 직접 넣지 않고 id만 넣는다.
        """
        deduped_entries = self._deduplicate_transaction_date_index_entries(entries)
        deduped_entries.sort(key=self._transaction_date_index_key, reverse=True)

        index_data = self._empty_transaction_date_index(order)
        if not deduped_entries:
            return index_data

        nodes: Dict[str, Dict[str, Any]] = {}
        leaf_ids: List[str] = []

        for chunk_start in range(0, len(deduped_entries), order):
            chunk = deduped_entries[chunk_start:chunk_start + order] # 4까지 자름
            leaf_id = self._make_transaction_date_index_node_id("leaf", len(nodes) + 1)
            leaf_ids.append(leaf_id)
            nodes[leaf_id] = {
                "id": leaf_id,
                "leaf": True,
                "keys": [self._transaction_date_index_key(entry) for entry in chunk],
                "entries": chunk,
                "next_leaf_id": None,
            }

        for current_id, next_id in zip(leaf_ids, leaf_ids[1:]):
            nodes[current_id]["next_leaf_id"] = next_id

        current_level_ids = leaf_ids
        while len(current_level_ids) > 1:
            next_level_ids: List[str] = []
            for chunk_start in range(0, len(current_level_ids), order):
                child_ids = current_level_ids[chunk_start:chunk_start + order]
                internal_id = self._make_transaction_date_index_node_id("node", len(nodes) + 1)
                nodes[internal_id] = {
                    "id": internal_id,
                    "leaf": False,
                    "keys": [nodes[child_id]["keys"][0] for child_id in child_ids],
                    "children": child_ids,
                }
                next_level_ids.append(internal_id)
            current_level_ids = next_level_ids

        index_data["root_id"] = current_level_ids[0]
        index_data["first_leaf_id"] = leaf_ids[0]
        index_data["nodes"] = nodes
        return index_data

    def _deduplicate_transaction_date_index_entries(
        self,
        entries: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        by_id: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            entry_id = entry.get("id")
            if not entry_id:
                continue
            by_id[entry_id] = {
                "date": entry["date"],
                "id": entry_id,
                "offset": entry["offset"],
            }
        return list(by_id.values())

    def _make_transaction_date_index_node_id(self, prefix: str, sequence: int) -> str:
        return f"{prefix}_{sequence:06d}"

    def _transaction_date_index_key(self, entry: Dict[str, Any]) -> str:
        # YYYY-MM-DD#id는 문자열 비교로 날짜순 정렬이 가능하다.
        return f'{entry["date"]}#{entry["id"]}'

    def _find_transaction_date_index_leaf_id(
        self,
        index_data: Dict[str, Any],
        key: str,
    ) -> Optional[str]:
        node_id = index_data.get("root_id")
        nodes = index_data.get("nodes", {})

        while node_id:
            node = nodes.get(node_id)
            if not node:
                return None
            if node.get("leaf"):
                return node_id

            keys = node.get("keys", [])
            children = node.get("children", [])
            if not keys or not children:
                return None

            child_index = 0
            # keys는 desc 정렬된 각 child의 max key다.
            # key가 다음 child의 max key보다 작거나 같으면 더 오른쪽 child로 내려간다.
            while child_index + 1 < len(keys) and key <= keys[child_index + 1]:
                child_index += 1
            node_id = children[child_index]

        return None

    def load_transaction_date_index_stream(self) -> Generator[Dict[str, Any], None, None]:
        """전체 index를 최신순으로 순회한다. leaf linked list를 사용한다."""
        index_data = self._load_transaction_date_index()
        nodes = index_data.get("nodes", {})
        leaf_id = index_data.get("first_leaf_id")

        while leaf_id:
            leaf = nodes.get(leaf_id)
            if not leaf:
                break
            for entry in leaf.get("entries", []):
                yield entry
            leaf_id = leaf.get("next_leaf_id")

    def load_transaction_date_index_range_stream(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        date desc index에서 범위 탐색을 수행한다.

        1. to_date가 있으면 to_date가 들어갈 leaf까지 root에서 seek한다.
        2. 그 leaf부터 next_leaf_id를 타고 내려간다.
        3. from_date보다 과거가 나오면 종료한다.
        """
        index_data = self._load_transaction_date_index()
        nodes = index_data.get("nodes", {})

        if to_date is None:
            leaf_id = index_data.get("first_leaf_id")
        else:
            # 같은 날짜 안에서는 가장 큰 id부터 시작해야 해당 날짜 전체를 포함한다.
            seek_key = f"{to_date}#\uffff"
            leaf_id = self._find_transaction_date_index_leaf_id(index_data, seek_key)

        while leaf_id:
            leaf = nodes.get(leaf_id)
            if not leaf:
                break

            for entry in leaf.get("entries", []):
                indexed_date = entry["date"]

                if to_date is not None and indexed_date > to_date:
                    continue

                if from_date is not None and indexed_date < from_date:
                    return

                yield entry

            leaf_id = leaf.get("next_leaf_id")

    def read_transaction_at_offset(self, offset: int) -> Transaction:
        with open(self.transactions_file, "rb") as f:
            f.seek(offset)
            line = f.readline().decode("utf-8")
        return Transaction.from_dict(json.loads(line))

    def load_transactions_stream(self) -> Generator[Transaction, None, None]:
        if not self.transactions_file.exists():
            return
        with open(self.transactions_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                yield Transaction.from_dict(json.loads(line))
