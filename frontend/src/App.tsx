import { useEffect, useState, useCallback } from "react";
import {
  fetchMerchants,
  fetchMerchant,
  fetchLedger,
  fetchBankAccounts,
  fetchPayouts,
  createPayout,
} from "./api";

type Merchant = { id: string; name: string };
type MerchantDetail = {
  id: string;
  name: string;
  balance: {
    available_balance_paise: number;
    held_balance_paise: number;
    total_credits_paise: number;
    total_debits_paise: number;
  };
};
type LedgerEntry = {
  id: string;
  entry_type: string;
  amount_paise: number;
  description: string;
  created_at: string;
};
type BankAccount = {
  id: string;
  account_number: string;
  ifsc_code: string;
  account_holder_name: string;
};
type Payout = {
  id: string;
  amount_paise: number;
  status: string;
  attempts: number;
  created_at: string;
  updated_at: string;
};

function paise(p: number) {
  return `₹${(p / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
}

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  processing: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
};

export default function App() {
  const [merchants, setMerchants] = useState<Merchant[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [detail, setDetail] = useState<MerchantDetail | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [payouts, setPayouts] = useState<Payout[]>([]);

  const [amountRupees, setAmountRupees] = useState("");
  const [bankAccountId, setBankAccountId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [flash, setFlash] = useState<{ type: "ok" | "err"; msg: string } | null>(null);

  useEffect(() => {
    fetchMerchants().then((data: Merchant[]) => {
      setMerchants(data);
      if (data.length > 0) setSelectedId(data[0].id);
    });
  }, []);

  const loadAll = useCallback(() => {
    if (!selectedId) return;
    fetchMerchant(selectedId).then(setDetail);
    fetchLedger(selectedId).then(setLedger);
    fetchBankAccounts(selectedId).then((accs: BankAccount[]) => {
      setAccounts(accs);
      if (accs.length > 0 && !bankAccountId) setBankAccountId(accs[0].id);
    });
    fetchPayouts(selectedId).then(setPayouts);
  }, [selectedId]);

  useEffect(() => {
    loadAll();
    const interval = setInterval(loadAll, 5000);
    return () => clearInterval(interval);
  }, [loadAll]);

  async function handlePayout(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId || !bankAccountId || !amountRupees) return;
    setSubmitting(true);
    setFlash(null);
    const key = crypto.randomUUID();
    const amountPaise = Math.round(parseFloat(amountRupees) * 100);
    const { status, data } = await createPayout(selectedId, amountPaise, bankAccountId, key);
    if (status === 201) {
      setFlash({ type: "ok", msg: `Payout created — ${paise(amountPaise)}` });
      setAmountRupees("");
      loadAll();
    } else {
      setFlash({ type: "err", msg: data.error || JSON.stringify(data) });
    }
    setSubmitting(false);
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-8 flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Playto Payout</h1>
        <select
          className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium shadow-sm"
          value={selectedId}
          onChange={(e) => {
            setSelectedId(e.target.value);
            setBankAccountId("");
          }}
        >
          {merchants.map((m) => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
      </header>

      {detail && (
        <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Card label="Available Balance" value={paise(detail.balance.available_balance_paise)} accent="text-green-700" />
          <Card label="Held Balance" value={paise(detail.balance.held_balance_paise)} accent="text-yellow-700" />
          <Card label="Total Credits" value={paise(detail.balance.total_credits_paise)} accent="text-blue-700" />
          <Card label="Total Debits" value={paise(detail.balance.total_debits_paise)} accent="text-red-700" />
        </div>
      )}

      <div className="mb-8 rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-semibold">Request Payout</h2>
        {flash && (
          <div className={`mb-4 rounded-lg px-4 py-2 text-sm ${flash.type === "ok" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
            {flash.msg}
          </div>
        )}
        <form onSubmit={handlePayout} className="flex flex-wrap items-end gap-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-500">Amount (₹)</label>
            <input
              type="number"
              step="0.01"
              min="1"
              className="w-40 rounded-lg border border-gray-300 px-3 py-2 text-sm"
              value={amountRupees}
              onChange={(e) => setAmountRupees(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-500">Bank Account</label>
            <select
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
              value={bankAccountId}
              onChange={(e) => setBankAccountId(e.target.value)}
              required
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.account_holder_name} — ****{a.account_number.slice(-4)}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-gray-900 px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-gray-800 disabled:opacity-50"
          >
            {submitting ? "Submitting..." : "Request Payout"}
          </button>
        </form>
      </div>

      <div className="grid gap-8 lg:grid-cols-2">
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <h2 className="border-b border-gray-100 px-6 py-4 text-lg font-semibold">Payout History</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-100 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-6 py-3">Amount</th>
                  <th className="px-6 py-3">Status</th>
                  <th className="px-6 py-3">Attempts</th>
                  <th className="px-6 py-3">Created</th>
                </tr>
              </thead>
              <tbody>
                {payouts.map((p) => (
                  <tr key={p.id} className="border-b border-gray-50">
                    <td className="px-6 py-3 font-medium">{paise(p.amount_paise)}</td>
                    <td className="px-6 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[p.status] || ""}`}>
                        {p.status}
                      </span>
                    </td>
                    <td className="px-6 py-3">{p.attempts}</td>
                    <td className="px-6 py-3 text-gray-500">{new Date(p.created_at).toLocaleString()}</td>
                  </tr>
                ))}
                {payouts.length === 0 && (
                  <tr><td colSpan={4} className="px-6 py-8 text-center text-gray-400">No payouts yet</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <h2 className="border-b border-gray-100 px-6 py-4 text-lg font-semibold">Ledger</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-gray-100 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-6 py-3">Type</th>
                  <th className="px-6 py-3">Amount</th>
                  <th className="px-6 py-3">Description</th>
                  <th className="px-6 py-3">Date</th>
                </tr>
              </thead>
              <tbody>
                {ledger.map((e) => (
                  <tr key={e.id} className="border-b border-gray-50">
                    <td className="px-6 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        e.entry_type === "credit" ? "bg-green-100 text-green-800" :
                        e.entry_type === "debit" ? "bg-red-100 text-red-800" :
                        e.entry_type === "hold" ? "bg-yellow-100 text-yellow-800" :
                        "bg-blue-100 text-blue-800"
                      }`}>
                        {e.entry_type}
                      </span>
                    </td>
                    <td className="px-6 py-3 font-medium">{paise(e.amount_paise)}</td>
                    <td className="px-6 py-3 text-gray-600">{e.description}</td>
                    <td className="px-6 py-3 text-gray-500">{new Date(e.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

function Card({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className={`mt-1 text-xl font-bold ${accent}`}>{value}</p>
    </div>
  );
}
