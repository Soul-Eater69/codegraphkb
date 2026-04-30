import axios from "axios";

export async function fetchOrder(id: string) {
  return await fetch(`/api/orders/${id}`, { method: "GET" });
}

export async function cancelOrderClient(id: string) {
  return await fetch("/api/orders/cancel", { method: "POST", body: JSON.stringify({ id }) });
}

export async function postOrderAxios(payload: any) {
  return axios.post("/api/orders", payload);
}

export async function loadOrdersAxios() {
  return axios.get("/api/orders");
}
