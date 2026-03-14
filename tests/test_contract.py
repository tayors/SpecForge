from __future__ import annotations

from pathlib import Path
import unittest

from formal_check.contract import ContractError, load_contract


FIXTURES = Path(__file__).parent / "fixtures" / "contracts"


class ContractTests(unittest.TestCase):
    def test_loads_valid_contract(self) -> None:
        contract = load_contract(FIXTURES / "valid")
        self.assertEqual(contract.project_name, "valid-example")
        self.assertEqual(list(contract.specs.keys()), ["quota"])
        self.assertEqual(contract.proof_obligations[0].objective, "sat_counterexample")

    def test_rejects_invalid_contract(self) -> None:
        with self.assertRaises(ContractError):
            load_contract(FIXTURES / "invalid")

    def test_impacted_specs_fall_back_to_all_when_no_mapping_hits(self) -> None:
        contract = load_contract(FIXTURES / "valid")
        self.assertEqual(contract.impacted_spec_ids(["src/unknown.py"]), ["quota"])


if __name__ == "__main__":
    unittest.main()
