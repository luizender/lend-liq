"""Endpoints, timeouts, and KLend on-chain layout constants."""

API_BASE = "https://api.kamino.finance"
DEFAULT_RPC = "https://api.mainnet-beta.solana.com"
USER_AGENT = "kamino-liq/0.1"

# Kamino Scope oracle — the same prices the protocol liquidates on.
PRICE_ENV = "mainnet-beta"
PRICE_SOURCE = "scope"

HTTP_TIMEOUT = 30
RPC_TIMEOUT = 40
RPC_MAX_ACCOUNTS = 100  # getMultipleAccounts caps at 100 keys per request

# KLend "scaled fraction" (Sf) fixed-point factor.
FRACTION_SCALE = 2**60

# Byte offsets inside the KLend Reserve account. RESERVE_LTV_OFFSET is read only
# to cross-check the layout against the API's maxLtv, so a program upgrade that
# shifts the struct fails loudly instead of returning a wrong threshold.
RESERVE_LTV_OFFSET = 4872  # ReserveConfig.loanToValuePct (u8) == API maxLtv
RESERVE_LIQ_THRESHOLD_OFFSET = 4873  # ReserveConfig.liquidationThresholdPct (u8)
MINT_DECIMALS_OFFSET = 44  # SPL mint account: decimals byte

# Sentinel marking an unused deposit/borrow slot in an obligation.
EMPTY_PUBKEY = "11111111111111111111111111111111"

# Symbols treated as price-stable in the market-crash scenario.
STABLE_SYMBOLS = frozenset(
    {
        "USDC", "USDT", "PYUSD", "USDG", "USDH", "FDUSD", "DAI",
        "USDS", "USDE", "SUSDE", "USDY", "EURC", "USDR", "USD*",
    }
)
