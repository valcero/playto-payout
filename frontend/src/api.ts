const BASE = "/api/v1";

export async function fetchMerchants() {
  const res = await fetch(`${BASE}/merchants/`);
  return res.json();
}

export async function fetchMerchant(id: string) {
  const res = await fetch(`${BASE}/merchants/${id}/`);
  return res.json();
}

export async function fetchLedger(merchantId: string) {
  const res = await fetch(`${BASE}/merchants/${merchantId}/ledger/`);
  return res.json();
}

export async function fetchBankAccounts(merchantId: string) {
  const res = await fetch(`${BASE}/merchants/${merchantId}/bank-accounts/`);
  return res.json();
}

export async function fetchPayouts(merchantId: string) {
  const res = await fetch(`${BASE}/merchants/${merchantId}/payouts/history/`);
  return res.json();
}

export async function createPayout(
  merchantId: string,
  amountPaise: number,
  bankAccountId: string,
  idempotencyKey: string
) {
  const res = await fetch(`${BASE}/merchants/${merchantId}/payouts/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({
      amount_paise: amountPaise,
      bank_account_id: bankAccountId,
    }),
  });
  return { status: res.status, data: await res.json() };
}
