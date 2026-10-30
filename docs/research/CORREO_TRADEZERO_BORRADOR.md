# Borrador de correo a TradeZero International (NO ENVIADO)

Para revisar por David antes de enviarlo. Destino: support@tradezero.co (soporte de TradeZero International).
Va en inglés porque el soporte de TZI responde en inglés. Rellenar lo que está entre corchetes.

---

**Subject:** Written confirmation: overnight shorts on regular locates, and API use by an unattended program

Hello,

I hold (or am opening) a TradeZero International margin account [account number, if any]. Before I trade, I need
written answers to the following questions so I can plan correctly.

**1. Overnight short positions on regular locates**

Your locates page (tradezero.com/locates) lists Regular Locates as "Intraday only (Must cover same-day)" and says
Pre-Borrows are for holding overnight, but Pre-Borrows are only offered for Reg SHO threshold securities. Your blog
article "What Is a Short Locate?" says that a short held past the 8:00 PM ET cutoff becomes an overnight borrow
subject to daily fees.

- a) If I short a hard-to-borrow stock that is not on the Reg SHO threshold list, using a Regular Locate, may I keep
  the position open overnight and for several days (up to about 20 trading days)?
- b) If yes, will TradeZero cover it automatically at some point, or only on a recall or buy-in?
- c) How is the overnight borrow fee for that position calculated (rate source, per 100-share lot, calendar days,
  three nights from Thursday), and where can I see the rate before entering?
- d) Is margin interest charged on short positions when the account has no debit balance? At what rate?
- e) For easy-to-borrow stocks, is there any limit on holding a short overnight?

**2. Using the API through an unattended program**

I plan to place orders through the TradeZero API from my own program running on a cloud server, on a schedule,
while I am not at my computer. The program would request locates, send short and cover orders (market and limit,
including AtTheOpening orders), and check positions. I would monitor it and keep a way to stop it.

- a) Is this use allowed under the API agreement for TradeZero International accounts?
- b) Are there any conditions: approval, minimum equity, API fees, request limits, or a requirement that I am
  present while it runs?
- c) Is there a paper or test environment where locates behave as on a live account?

**3. Other rules that affect the plan**

- a) The rule that levered accounts may not hold more than 2 to 1 leverage into the 4 PM ET close: is it checked on
  short market value against equity at 3:45 PM ET, and how does TradeZero reduce positions that exceed it?
- b) Minimum equity to keep shorting with margin on a TradeZero International account.
- c) Is real-time market data available through the API, and at what cost?

Thank you. Please reply in writing so I can keep the answers on file.

Kind regards,
[Name]
[Account number / email on file]

---

Fuentes de las dudas: tradezero.com/locates (tabla de tipos de locate), el artículo del blog de TradeZero sobre
locates (septiembre 2026) y docs/research/REVISION_ESTRATEGIA_ES.md.
