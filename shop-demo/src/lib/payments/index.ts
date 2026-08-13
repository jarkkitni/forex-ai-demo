import { mockDriver } from "./mock";
import { stripeDriver } from "./stripe";
import type { PaymentDriver } from "./types";

export function driver(): PaymentDriver {
  return process.env.PAYMENT_DRIVER === "stripe" ? stripeDriver : mockDriver;
}

export type { PaymentDriver, ChargeResult } from "./types";
