import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from evm_forecaster import Period, compute, earned_schedule, load_csv, render_markdown, render_svg, tcpi_verdict  # noqa: E402

SAMPLE = HERE.parent / "data" / "sample_program.csv"


class EarnedScheduleTests(unittest.TestCase):
    def test_interpolates_between_periods(self):
        # EV of 150 sits halfway between PV of 100 (period 1) and 200 (period 2)
        self.assertAlmostEqual(earned_schedule([100, 200, 300], 150), 1.5)

    def test_inside_first_period(self):
        self.assertAlmostEqual(earned_schedule([100, 200], 50), 0.5)

    def test_ev_at_or_beyond_final_pv(self):
        self.assertEqual(earned_schedule([100, 200], 200), 2.0)
        self.assertEqual(earned_schedule([100, 200], 250), 2.0)

    def test_flat_pv_does_not_divide_by_zero(self):
        self.assertEqual(earned_schedule([100, 100, 200], 100), 2.0)


class ComputeTests(unittest.TestCase):
    def setUp(self):
        self.r = compute(load_csv(SAMPLE))

    def test_core_indices(self):
        self.assertEqual(self.r["status_period"], 9)
        self.assertEqual(self.r["bac"], 4800)
        self.assertAlmostEqual(self.r["cpi"], 1990 / 2240)
        self.assertAlmostEqual(self.r["spi"], 1990 / 2320)
        self.assertEqual(self.r["cv"], -250)
        self.assertEqual(self.r["sv"], -330)

    def test_eac_methods(self):
        eac = self.r["eac"]
        self.assertAlmostEqual(eac["remaining at budget rate"], 2240 + 2810)
        self.assertAlmostEqual(eac["current CPI continues"], 4800 / (1990 / 2240))
        cpi, spi = 1990 / 2240, 1990 / 2320
        self.assertAlmostEqual(eac["CPI x SPI pressure"], 2240 + 2810 / (cpi * spi))

    def test_tcpi(self):
        self.assertAlmostEqual(self.r["tcpi_bac"], 2810 / 2560)

    def test_earned_schedule_forecast(self):
        self.assertAlmostEqual(self.r["es"], 8 + 10 / 340)
        self.assertAlmostEqual(self.r["ieac_t"], 18 / (self.r["es"] / 9))

    def test_status_period_override(self):
        r = compute(load_csv(SAMPLE), status_period=4)
        self.assertEqual(r["ev"], 640)
        self.assertEqual(len(r["trend"]), 4)

    def test_missing_status_period_raises(self):
        with self.assertRaises(ValueError):
            compute(load_csv(SAMPLE), status_period=12)

    def test_no_actuals_raises(self):
        with self.assertRaises(ValueError):
            compute([Period(1, 100, None, None)])


class OutputTests(unittest.TestCase):
    def test_verdict_thresholds(self):
        self.assertEqual(tcpi_verdict(0.95, 0.98), "achievable")
        self.assertEqual(tcpi_verdict(0.95, 1.03), "aggressive")
        self.assertEqual(tcpi_verdict(0.89, 1.10), "not credible")
        self.assertIn("not meaningful", tcpi_verdict(0.9, None))

    def test_report_leads_with_bottom_line(self):
        report = render_markdown(compute(load_csv(SAMPLE)))
        body = report.split("\n", 4)[-1]
        self.assertTrue(body.startswith("**Bottom line:**"))
        self.assertIn("not credible", report)

    def test_svg_renders(self):
        periods = load_csv(SAMPLE)
        svg = render_svg(periods, compute(periods))
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.endswith("</svg>"))


if __name__ == "__main__":
    unittest.main()
