import express from "express";
import { cancelOrderHandler } from "../controllers/order.controller";

const router = express.Router();

router.post("/orders/:id/cancel", cancelOrderHandler);

export default router;
