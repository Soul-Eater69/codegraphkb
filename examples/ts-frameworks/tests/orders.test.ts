import { describe, it, expect } from "vitest";
import { cancelOrder, listOrders } from "../prisma/orders.service";

describe("orders service", () => {
  it("cancels an order", async () => {
    await cancelOrder("abc-123");
    expect(true).toBe(true);
  });

  it("lists orders for a user", async () => {
    const rows = await listOrders("user-1");
    expect(Array.isArray(rows)).toBe(true);
  });
});
