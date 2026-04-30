import { describe, it, expect } from "vitest";
import { cancelOrder } from "../services/order.service";

describe("cancel flow", () => {
  it("cancels an order", () => {
    const out = cancelOrder({ orderId: "1", reason: "test" });
    expect(out.ok).toBe(true);
  });
});
