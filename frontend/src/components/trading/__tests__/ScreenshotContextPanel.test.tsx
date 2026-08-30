import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ScreenshotContextPanel } from "../ScreenshotContextPanel";

describe("ScreenshotContextPanel", () => {
  it("renders HTF context for the tactical symbol instead of the first row", () => {
    render(<ScreenshotContextPanel
      symbol="QQQ"
      htf={{
        status: "context_available",
        source: {} as never,
        items: [
          { symbol: "SPY", primary_bias: "bullish", allowed_playbooks: [], reassessment_reasons: [], source_labels: [], execution_enabled: false, can_submit_orders: false },
          { symbol: "QQQ", primary_bias: "bearish", allowed_playbooks: [], reassessment_reasons: [], source_labels: [], execution_enabled: false, can_submit_orders: false },
        ],
        closed_bar_only: true,
        score_effect: "context_only",
        message: "context",
        execution_enabled: false,
        can_submit_orders: false,
      }}
    />);

    expect(screen.getByText(/QQQ · bearish/i)).toBeInTheDocument();
    expect(screen.queryByText(/SPY · bullish/i)).not.toBeInTheDocument();
  });
});
