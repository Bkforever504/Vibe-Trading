import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useHotkeys } from "../useHotkeys";

function Harness({ refresh, selectTab }: { refresh: () => void; selectTab: (index: number) => void }) {
  useHotkeys(true, { refresh, selectTab });
  return <div />;
}

describe("useHotkeys", () => {
  it("maps refresh and numbered tabs", () => {
    const refresh = vi.fn(); const selectTab = vi.fn();
    render(<Harness refresh={refresh} selectTab={selectTab} />);
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "r" }));
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "3" }));
    expect(refresh).toHaveBeenCalledOnce();
    expect(selectTab).toHaveBeenCalledWith(2);
  });
});

