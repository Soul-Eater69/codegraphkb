export async function cancelOrderClient(id: string, reason: string) {
  const res = await fetch("/orders/:id/cancel", {
    method: "POST",
    body: JSON.stringify({ id, reason }),
  });
  return res.json();
}
