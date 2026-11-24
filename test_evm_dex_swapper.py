import unittest

from services.evm_dex_swapper import _price_impact_pct


class TestPriceImpact(unittest.TestCase):
    def test_kyberswap_summary_with_empty_fee_amount(self):
        # Shape KyberSwap returns when no extra fee is charged; float("") used to abort every swap.
        summary = {
            "amountInUsd": "100",
            "amountOutUsd": "97.5",
            "extraFee": {"feeAmount": "", "chargeFeeBy": "", "isInBps": False, "feeReceiver": ""},
        }
        self.assertAlmostEqual(_price_impact_pct(summary), 2.5)

    def test_missing_or_malformed_usd_values_give_zero(self):
        for summary in ({}, {"amountInUsd": "", "amountOutUsd": ""}, {"amountInUsd": "abc", "amountOutUsd": "1"}, {"amountInUsd": "0", "amountOutUsd": "5"}):
            self.assertEqual(_price_impact_pct(summary), 0.0, summary)

    def test_favourable_route_is_not_negative(self):
        self.assertEqual(_price_impact_pct({"amountInUsd": "100", "amountOutUsd": "101"}), 0.0)


if __name__ == "__main__":
    unittest.main()
