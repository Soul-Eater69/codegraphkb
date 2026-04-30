import express from "express";
import { authMiddleware } from "./middleware";

const router = express.Router();

export function cancelOrderHandler(req: any, res: any) {
  res.json({ ok: true });
}

router.post("/orders/:id/cancel", authMiddleware, cancelOrderHandler);
router.get("/orders", cancelOrderHandler);
