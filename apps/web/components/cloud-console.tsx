"use client";
// The student cloud console shell: capability-filtered service navigation + the selected service's
// console. Every cloud operation goes through CloudLabs FastAPI service endpoints (never to an emulator).
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CONSOLE_CSS, type Feature } from "./console-kit";
import { DynamoDbConsole } from "./dynamodb-console";
import { Ec2Console } from "./ec2-console";
import { IamConsole } from "./iam-console";
import { LambdaConsole } from "./lambda-console";
import { S3Console } from "./s3-console";
import { SnsConsole } from "./sns-console";
import { SqsConsole } from "./sqs-console";
import { VpcConsole } from "./vpc-console";

type Services = { services: Record<string, string>; features: Record<string, Record<string, Feature>> };
const SERVICE_LABEL: Record<string, string> = { s3: "S3", ec2: "EC2", vpc: "VPC", sqs: "SQS", sns: "SNS", iam: "IAM", lambda: "Lambda",
  dynamodb: "DynamoDB" };
const SERVICE_ORDER = ["s3", "dynamodb", "iam", "ec2", "vpc", "sqs", "sns", "lambda"];

export function CloudConsole({ sessionId, readOnly, initial = "s3" }: { sessionId: string; readOnly: boolean; initial?: string }) {
  const [services, setServices] = useState<Services | null>(null);
  const [service, setService] = useState(initial);
  useEffect(() => {
    void api<Services>(`/api/console/services?session_id=${sessionId}`).then(setServices).catch(() => undefined);
  }, [sessionId]);
  const available = (svc: string) => (services?.services[svc] ?? (svc === initial ? "available" : "")) === "available";

  return (
    <div className="console">
      <nav className="svc-nav" aria-label="Services">
        <div className="eyebrow" style={{ padding: "0 10px 6px" }}>Services</div>
        {SERVICE_ORDER.filter((s) => !services || s in services.services).map((svc) => (
          <button key={svc} className={`svc ${svc === service ? "active" : ""}`} disabled={!available(svc)}
            aria-current={svc === service ? "page" : undefined} onClick={() => setService(svc)} data-testid={`svc-${svc}`}>
            <span>{SERVICE_LABEL[svc]}</span>
            {!available(svc) && <span className="soon">Not in this lab</span>}
          </button>
        ))}
      </nav>
      {service === "dynamodb"
        ? <DynamoDbConsole sessionId={sessionId} readOnly={readOnly} features={services?.features.dynamodb ?? {}} />
        : service === "iam"
          ? <IamConsole sessionId={sessionId} readOnly={readOnly} features={services?.features.iam ?? {}} />
        : service === "ec2"
          ? <Ec2Console sessionId={sessionId} readOnly={readOnly} features={services?.features.ec2 ?? {}} />
        : service === "vpc"
          ? <VpcConsole sessionId={sessionId} readOnly={readOnly} features={services?.features.vpc ?? {}} />
        : service === "sqs"
          ? <SqsConsole sessionId={sessionId} readOnly={readOnly} features={services?.features.sqs ?? {}} />
        : service === "sns"
          ? <SnsConsole sessionId={sessionId} readOnly={readOnly} features={services?.features.sns ?? {}} />
        : service === "lambda"
          ? <LambdaConsole sessionId={sessionId} readOnly={readOnly} features={services?.features.lambda ?? {}} />
          : <S3Console sessionId={sessionId} readOnly={readOnly} features={services?.features.s3 ?? {}} />}
      <style>{CONSOLE_CSS}</style>
    </div>
  );
}
