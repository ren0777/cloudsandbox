"""Lambda evaluation (PLAN emulator strategy §4): can each engine execute the Lambda lab behaviour
*inside a hardened sandbox with no Docker socket*? Run inside api-test with PYTHONPATH=/srv."""
import asyncio
import io
import json
import time
import uuid
import zipfile

from app.config import get_settings
from app.runtime import emulators
from app.runtime.runner_client import HttpRunnerClient

CODE_V1 = "def lambda_handler(event, context):\n    return {'message': 'hello ' + event.get('name', 'world')}\n"
CODE_V2 = ("import os\n\ndef lambda_handler(event, context):\n"
           "    total = sum(i['price'] * i['qty'] for i in event['items'])\n"
           "    return {'total': round(total * (1 + float(os.environ['TAX_RATE'])), 2)}\n")
CODE_ERR = "def lambda_handler(event, context):\n    raise ValueError('boom')\n"
TRUST = json.dumps({"Version": "2012-10-17", "Statement": [
    {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]})


def zipped(src: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("lambda_function.py", src)
    return buf.getvalue()


def ops(lam, iam, st):
    def invoke(payload):
        t = time.time()
        r = lam.invoke(FunctionName="orders", Payload=json.dumps(payload).encode())
        body = r["Payload"].read().decode()
        print(f"     invoke -> {r.get('StatusCode')} err={r.get('FunctionError')} {body[:80]} ({time.time()-t:.1f}s)")
        return r, body

    return [
        ("iam CreateRole", lambda: st.__setitem__("role", iam.create_role(RoleName="fn-role", AssumeRolePolicyDocument=TRUST)["Role"]["Arn"])),
        ("CreateFunction(python3.12)", lambda: lam.create_function(FunctionName="orders", Runtime="python3.12", Role=st["role"],
                                                                  Handler="lambda_function.lambda_handler", Code={"ZipFile": zipped(CODE_V1)})),
        ("GetFunctionConfiguration", lambda: lam.get_function_configuration(FunctionName="orders")["Runtime"] == "python3.12" or 1 / 0),
        ("ListFunctions", lambda: [f["FunctionName"] for f in lam.list_functions()["Functions"]] == ["orders"] or 1 / 0),
        ("Invoke v1 (executes code)", lambda: '"hello cafe"' in invoke({"name": "cafe"})[1] or 1 / 0),
        ("UpdateFunctionCode", lambda: lam.update_function_code(FunctionName="orders", ZipFile=zipped(CODE_V2))),
        ("UpdateFunctionConfiguration(env)", lambda: lam.update_function_configuration(FunctionName="orders", Environment={"Variables": {"TAX_RATE": "0.08"}},
                                                                                      MemorySize=256, Timeout=10)),
        ("GetFunction(code location)", lambda: print("     code:", lam.get_function(FunctionName="orders")["Code"].get("Location", "")[:90])),
        ("Invoke v2 (new code + env)", lambda: '6.48' in invoke({"items": [{"price": 3, "qty": 2}]})[1] or 1 / 0),
        ("Invoke error -> FunctionError", lambda: (lam.update_function_code(FunctionName="orders", ZipFile=zipped(CODE_ERR)),
                                                  invoke({})[0].get("FunctionError") == "Unhandled" or 1 / 0)),
        ("DeleteFunction", lambda: lam.delete_function(FunctionName="orders")),
    ]


async def main():
    s = get_settings()
    r = HttpRunnerClient(s.runner_id, s.runner_url, s.runner_secret, 150)
    for eng in ("floci", "moto", "ministack"):
        sid = str(uuid.uuid4())
        info = await r.create_sandbox({"sandbox_id": sid, "env": s.env, "engine": eng, "terminal_credential": "probe:abcdefgh1234"})
        a = emulators.get(eng) if eng in emulators.ENGINES else emulators.EmulatorAdapter(eng)
        lam, iam = a.client("lambda", info["emulator_endpoint"]), a.client("iam", info["emulator_endpoint"])
        st: dict = {}
        for name, fn in ops(lam, iam, st):
            try:
                await asyncio.to_thread(fn)
                print(f"{eng:<9} PASS {name}")
            except Exception as e:
                print(f"{eng:<9} FAIL {name}: {str(e)[:130]}")
        await r.destroy_sandbox(sid)


asyncio.run(main())
