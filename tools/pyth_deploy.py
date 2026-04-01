"""Deploy Solidity contracts to Base Sepolia using Foundry (forge)."""

import json
import os
import subprocess

SCHEMA = {
    "name": "pyth_deploy",
    "description": (
        "Compile and deploy a Solidity smart contract to Base Sepolia using Foundry. "
        "Runs 'forge build' to compile, then 'forge create' to deploy. "
        "Returns the deployed contract address, transaction hash, and BaseScan explorer link. "
        "Requires Foundry (forge) to be installed and DEPLOYER_PRIVATE_KEY env var to be set. "
        "The Pyth Entropy contract on Base Sepolia is at 0x4821932D0CDd71225A6d914706A621e0389D7061."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contract": {
                "type": "string",
                "description": (
                    "Contract to deploy, in 'path:ContractName' format. "
                    "Example: 'src/CoinFlip.sol:CoinFlip'"
                ),
            },
            "constructor_args": {
                "type": "string",
                "description": (
                    "Space-separated constructor arguments. "
                    "Example: '0x4821932D0CDd71225A6d914706A621e0389D7061 0xProviderAddr'"
                ),
            },
        },
        "required": ["contract"],
    },
}

BASE_SEPOLIA_ENTROPY = "0x4821932D0CDd71225A6d914706A621e0389D7061"
BASESCAN_URL = "https://sepolia.basescan.org"


def handle(args: dict, working_dir: str | None = None) -> str:
    contract = args.get("contract", "")
    constructor_args = args.get("constructor_args", "")

    if not contract:
        return json.dumps({"error": "contract is required (e.g. 'src/CoinFlip.sol:CoinFlip')"})

    rpc_url = os.environ.get("BASE_SEPOLIA_RPC", "https://sepolia.base.org")
    private_key = os.environ.get("DEPLOYER_PRIVATE_KEY", "")

    if not private_key:
        return json.dumps({"error": "DEPLOYER_PRIVATE_KEY environment variable is not set"})

    workdir = working_dir or os.getcwd()

    # Step 1: Compile with forge build
    try:
        build_result = subprocess.run(
            ["forge", "build"],
            capture_output=True,
            text=True,
            cwd=workdir,
            timeout=120,
        )
        if build_result.returncode != 0:
            return json.dumps({
                "error": "Compilation failed",
                "stderr": build_result.stderr,
                "stdout": build_result.stdout,
            })
    except FileNotFoundError:
        return json.dumps({"error": "Foundry (forge) is not installed. Install it: curl -L https://foundry.paradigm.xyz | bash && foundryup"})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "forge build timed out after 120 seconds"})

    # Step 2: Deploy with forge create
    cmd = [
        "forge", "create",
        contract,
        "--rpc-url", rpc_url,
        "--private-key", private_key,
        "--broadcast",
    ]

    if constructor_args:
        cmd.append("--constructor-args")
        cmd.extend(constructor_args.split())

    try:
        deploy_result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=workdir,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "forge create timed out after 120 seconds"})

    output = deploy_result.stdout + "\n" + deploy_result.stderr

    if deploy_result.returncode != 0:
        return json.dumps({
            "error": "Deployment failed",
            "output": output,
        })

    # Parse deployed address and tx hash from forge output
    deployed_to = ""
    tx_hash = ""
    for line in output.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("Deployed to:"):
            deployed_to = line_stripped.split(":", 1)[1].strip()
        elif line_stripped.startswith("Transaction hash:"):
            tx_hash = line_stripped.split(":", 1)[1].strip()

    if not deployed_to:
        return json.dumps({
            "error": "Could not parse deployed address from forge output",
            "output": output,
        })

    result_lines = [
        "Contract deployed successfully to Base Sepolia!",
        "",
        f"  Contract:    {contract}",
        f"  Address:     {deployed_to}",
        f"  Tx Hash:     {tx_hash}",
        f"  Explorer:    {BASESCAN_URL}/address/{deployed_to}",
        f"  Tx Link:     {BASESCAN_URL}/tx/{tx_hash}",
        "",
        f"  Pyth Entropy (Base Sepolia): {BASE_SEPOLIA_ENTROPY}",
        f"  RPC:         {rpc_url}",
    ]
    return "\n".join(result_lines)


def register(reg):
    reg.register("pyth_deploy", SCHEMA, handle)
