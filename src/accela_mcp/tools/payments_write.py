"""Payment write tools — initiate and commit.

Two tools:

  * `accela_initiate_payment` — POST /v4/payments. Creates a pending
    payment intent. Reversible (the agency can cancel before commit).
  * `accela_commit_payment` — POST /v4/payments/{id}/commit. The
    irreversible step. **Will not call without `confirm=True` AND
    `payments.real_money_allowed=true` in capabilities.yaml.** PROD
    environments additionally require the
    `i_understand_this_spends_real_money` flag (validated at config-load).

The split mirrors what most checkout flows do under the hood — building
in a deliberate pause where the agency can verify the amount and
beneficiary before committing.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from accela_mcp.safety import WritePreview, write_tool
from accela_mcp.tools._base import ToolContext


def register(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool()
    @write_tool("accela_initiate_payment", ctx, affects_money=True)
    async def accela_initiate_payment(
        record_id: str,
        amount: float,
        payment_method: str,
        payer_name: str | None = None,
        reference: str | None = None,
        currency: str = "USD",
        confirm: bool = False,
    ) -> WritePreview | dict[str, Any]:
        """⚠️ **Initiates a financial transaction.** Default is dry-run —
        show the returned preview to the human user and only re-invoke
        with `confirm=True` after they approve.

        Creates a *pending* payment on a record. Does NOT actually move
        money — call `accela_commit_payment` afterward to do that. The
        intermediate state lets the agency reconcile the request before
        committing. `payment_method` is agency-defined."""
        if not record_id or not record_id.strip():
            raise ValueError("record_id is required")
        if amount is None or float(amount) <= 0:
            raise ValueError("amount must be a positive number")
        if not payment_method or not payment_method.strip():
            raise ValueError("payment_method is required")

        body: dict[str, Any] = {
            "recordId": {"id": record_id},
            "amount": float(amount),
            "currency": currency,
            "paymentMethod": payment_method,
        }
        if payer_name:
            body["payerName"] = payer_name
        if reference:
            body["reference"] = reference

        path = "/v4/payments"
        if not confirm:
            return WritePreview(
                tool="accela_initiate_payment",
                method="POST",
                path=path,
                summary=(
                    f"Initiate {currency} {amount} payment on record {record_id!r} "
                    f"via {payment_method!r} (pending — does NOT yet move money)"
                ),
                body=body,
                affects_money=True,
            )

        response = await ctx.client.post(path, json=body)
        return {
            "method": "POST",
            "path": path,
            "request_body": body,
            "result_status": int(response.get("status", 200)),
            "result_id": _result_id(response),
            "trace_id": response.get("traceId"),
            "result": response.get("result"),
        }

    @mcp.tool()
    @write_tool("accela_commit_payment", ctx, affects_money=True)
    async def accela_commit_payment(
        payment_id: str,
        confirm: bool = False,
    ) -> WritePreview | dict[str, Any]:
        """⚠️ **Irreversibly commits a pending payment — moves real money.**
        Default is dry-run. Refuses to execute unless capabilities.yaml has
        `payments.real_money_allowed: true` (and against PROD-like
        environments, also requires `i_understand_this_spends_real_money:
        true`). Show the preview to the user, get explicit approval, then
        re-invoke with `confirm=True`."""
        if not payment_id or not str(payment_id).strip():
            raise ValueError("payment_id is required")

        body: dict[str, Any] = {"id": payment_id}
        path = f"/v4/payments/{payment_id}/commit"

        if not confirm:
            warnings: list[str] = ["Irreversible — money moves after this commit."]
            if not ctx.payments_config.real_money_allowed:
                warnings.append(
                    "payments.real_money_allowed is FALSE — calling with "
                    "confirm=true will be refused. Update capabilities.yaml first."
                )
            return WritePreview(
                tool="accela_commit_payment",
                method="POST",
                path=path,
                summary=f"Commit payment {payment_id!r} (irreversible)",
                body=body,
                irreversible=True,
                affects_money=True,
                warnings=warnings,
            )

        # Extra gate beyond the standard kill-switch: even with writes
        # enabled, refuse to commit without explicit real-money permission.
        if not ctx.payments_config.real_money_allowed:
            return {
                "error": "payments_disabled",
                "message": (
                    "Refusing to commit payment: capabilities.yaml has "
                    "`payments.real_money_allowed: false`. Lifting this gate "
                    "is intentional friction; set it to true (and the PROD "
                    "friction flag if applicable) before committing real "
                    "transactions."
                ),
                "payment_id": payment_id,
            }

        response = await ctx.client.post(path, json=body)
        return {
            "method": "POST",
            "path": path,
            "request_body": body,
            "result_status": int(response.get("status", 200)),
            "result_id": payment_id,
            "trace_id": response.get("traceId"),
            "result": response.get("result"),
        }


def _result_id(response: dict[str, Any]) -> str | None:
    result = response.get("result")
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            value = first.get("id")
            if value is not None:
                return str(value)
    if isinstance(result, dict):
        value = result.get("id")
        if value is not None:
            return str(value)
    return None
