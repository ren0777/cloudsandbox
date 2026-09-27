// Stackora public landing page. Marketing only: the authenticated application lives behind /login, so this
// page never reads session state or redirects. Keep it a server component (no client hooks needed).
import Link from "next/link";

const SERVICES = [
  { name: "S3", line: "Buckets, versioning, policies, objects" },
  { name: "DynamoDB", line: "Tables, items, on-demand capacity" },
  { name: "IAM", line: "Users, groups, roles, policy simulator" },
  { name: "EC2", line: "Instances, security groups, key pairs" },
  { name: "Lambda", line: "Functions, configuration, invocations" },
];

const FEATURES = [
  {
    title: "AWS-style console + real AWS CLI",
    line: "Students work in a faithful console or the real AWS CLI in a browser terminal — both act on the same sandbox.",
    icon: "console",
  },
  {
    title: "Isolated per-student sandboxes",
    line: "One private network per student, no internet, no AWS account, CPU/memory/PID limits, read-only rootfs.",
    icon: "box",
  },
  {
    title: "Deterministic auto-grading",
    line: "Grading is a pure function of immutable evidence captured from the sandbox: same state, same marks, every time.",
    icon: "check",
  },
  {
    title: "Instructor Lab Builder",
    line: "Create, clone or import a lab, edit it with generated forms and YAML, test it in real sandboxes and publish.",
    icon: "builder",
  },
  {
    title: "Break-fix labs",
    line: "Start from a broken environment built from typed actions — students diagnose and repair it, not just build it.",
    icon: "wrench",
  },
  {
    title: "Live architecture diagrams",
    line: "A diagram of what the student actually built, updated as the sandbox changes, and stored with the result.",
    icon: "graph",
  },
  {
    title: "Simulated cost awareness",
    line: "An educational cost meter shows what the architecture would cost, with a clear 'not AWS billing' label.",
    icon: "cost",
  },
  {
    title: "Multi-runner, self-hosted",
    line: "Scheduler, drain/maintenance, gateway mode and deployment docs for one server or a runner fleet.",
    icon: "fleet",
  },
  {
    title: "Open source, Apache-2.0",
    line: "Run the whole platform on your own hardware. No vendor lock-in, no per-seat pricing, no student data leaving campus.",
    icon: "oss",
  },
];

function Icon({ name }: { name: string }) {
  const paths: Record<string, React.ReactNode> = {
    console: <><rect x="3" y="4" width="18" height="14" rx="2" /><path d="M3 9h18M7 13l2 2-2 2M12 17h5" /></>,
    box: <><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z" /><path d="M4 7.5l8 4.5 8-4.5M12 12v9" /></>,
    check: <><circle cx="12" cy="12" r="9" /><path d="M8 12.5l2.5 2.5L16 9.5" /></>,
    builder: <><path d="M4 20h16M6 20V9l6-5 6 5v11" /><path d="M10 20v-6h4v6" /></>,
    wrench: <><path d="M14.5 6.5a4 4 0 105.3 5.3L21 11l-3-3-1.5.8a4 4 0 00-2-2.3z" /><path d="M13 11L4 20l-1-1 9-9" /></>,
    graph: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /><path d="M10 6.5h4a3.5 3.5 0 013.5 3.5v4" /></>,
    cost: <><circle cx="12" cy="12" r="9" /><path d="M15 9.5c0-1.4-1.3-2.5-3-2.5s-3 1-3 2.3c0 3.4 6 1.7 6 5.2 0 1.3-1.3 2.3-3 2.3s-3-1-3-2.4M12 5.5v13" /></>,
    fleet: <><rect x="3" y="4" width="18" height="6" rx="1.5" /><rect x="3" y="14" width="18" height="6" rx="1.5" /><path d="M7 7h.01M7 17h.01" /></>,
    oss: <><path d="M12 2l3 6 6 .9-4.5 4.3 1.1 6.3L12 16.5 6.4 19.5l1.1-6.3L3 8.9 9 8z" /></>,
  };
  return <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden>{paths[name]}</svg>;
}

const SHOTS = [
  { src: "/screenshots/landing-lab.png", alt: "Student lab briefing", cap: "A lab briefing: personal variables, hints and marks." },
  { src: "/screenshots/landing-console.png", alt: "AWS-style S3 console", cap: "The AWS-style console, acting on the student's sandbox." },
  { src: "/screenshots/landing-architecture.png", alt: "Live architecture diagram", cap: "The live architecture diagram, from real sandbox state." },
  { src: "/screenshots/landing-builder.png", alt: "Instructor Lab Builder", cap: "The Lab Builder: generated check forms and validation." },
];

export default function Landing() {
  return (
    <div className="lp">
      <header className="lp-nav">
        <div className="lp-wrap lp-nav-in">
          <Link href="/" className="lp-brand"><span className="lp-dot" aria-hidden />Stackora</Link>
          <nav aria-label="Landing">
            <a href="#features">Features</a>
            <a href="#services">Services</a>
            <a href="#screens">Screenshots</a>
            <a href="#open-source">Open source</a>
          </nav>
          <div className="lp-nav-cta">
            <Link href="/login" className="lp-btn ghost">Sign in</Link>
            <Link href="/login" className="lp-btn primary" data-testid="cta-try">Try the demo</Link>
          </div>
        </div>
      </header>

      <section className="lp-hero">
        <div className="lp-wrap lp-hero-in">
          <div className="lp-hero-copy">
            <span className="lp-eyebrow">Cloud labs for the classroom</span>
            <h1>Stackora</h1>
            <p className="lp-tag">Launch it. Break it. Fix it.</p>
            <p className="lp-sub">Hands-on cloud labs with real CLI workflows and instant grading.</p>
            <div className="lp-ctas">
              <Link href="/login" className="lp-btn primary lg" data-testid="cta-primary">Try the demo</Link>
              <Link href="/login?next=/instructor" className="lp-btn outline lg" data-testid="cta-instructor">For instructors</Link>
            </div>
            <p className="lp-note">Runs entirely on your hardware · No AWS account · Apache-2.0</p>
          </div>
          <div className="lp-hero-art" aria-hidden>
            <div className="lp-term">
              <div className="lp-term-bar"><span /><span /><span /><em>student@stackora:~</em></div>
              <pre>{`$ aws s3 mb s3://cafe-demo01-site
make_bucket: cafe-demo01-site
$ aws s3api put-bucket-versioning \\
    --bucket cafe-demo01-site \\
    --versioning-configuration Status=Enabled
$ aws s3 cp index.html s3://cafe-demo01-site/
upload: ./index.html to s3://cafe-demo01-site/index.html`}</pre>
            </div>
            <div className="lp-grade">
              <span className="lp-grade-ring">100</span>
              <div><strong>Graded automatically</strong><div className="lp-small">Create the bucket · versioning · upload · tag</div></div>
            </div>
          </div>
        </div>
      </section>

      <section className="lp-strip" id="services">
        <div className="lp-wrap">
          <p className="lp-strip-title">Supported AWS services</p>
          <div className="lp-services">
            {SERVICES.map((s) => (
              <div className="lp-service" key={s.name}>
                <span className="lp-svc-name">{s.name}</span>
                <span className="lp-small">{s.line}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section" id="features">
        <div className="lp-wrap">
          <span className="lp-eyebrow">The platform</span>
          <h2>Everything a cloud course needs, in one place</h2>
          <p className="lp-lede">Students get a real cloud to work in. Instructors get evidence they can trust.</p>
          <div className="lp-grid">
            {FEATURES.map((f) => (
              <article className="lp-card" key={f.title}>
                <span className="lp-ic"><Icon name={f.icon} /></span>
                <h3>{f.title}</h3>
                <p>{f.line}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-workflow">
        <div className="lp-wrap lp-workflow-in">
          <div>
            <span className="lp-eyebrow">Two ways to work</span>
            <h2>A faithful console and the real AWS CLI</h2>
            <p className="lp-lede">Both act on the same isolated sandbox, so students can click their way through
              the console and then prove it in the terminal — exactly like the real thing.</p>
            <ul className="lp-list">
              <li><strong>Console:</strong> S3, DynamoDB, IAM, EC2 and Lambda pages with AWS terminology and workflows.</li>
              <li><strong>CLI:</strong> AWS CLI v2 in a browser terminal, authenticated to the sandbox only.</li>
              <li><strong>Same state:</strong> what the console creates, the CLI sees — and grading reads it all.</li>
            </ul>
          </div>
          <div className="lp-workflow-art" aria-hidden>
            <pre>{`# the student's cloud, no account required
$ aws iam attach-group-policy \\
    --group-name baristas-demo01 \\
    --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
# ...a break-fix lab waiting to be repaired
$ aws iam detach-group-policy ...   ✓ fixed`}</pre>
          </div>
        </div>
      </section>

      <section className="lp-section alt" id="screens">
        <div className="lp-wrap">
          <span className="lp-eyebrow">Screenshots</span>
          <h2>See it in action</h2>
          <p className="lp-lede">Every screenshot below is produced by the automated end-to-end suite, not a mockup.</p>
          <div className="lp-shots">
            {SHOTS.map((s) => (
              <figure className="lp-shot" key={s.src}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={s.src} alt={s.alt} loading="lazy" />
                <figcaption>{s.cap}</figcaption>
              </figure>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section" id="open-source">
        <div className="lp-wrap lp-oss">
          <div>
            <span className="lp-eyebrow">Open source</span>
            <h2>Apache-2.0. Yours to run.</h2>
            <p className="lp-lede">Stackora is open source under the Apache License 2.0. Deploy it on one server or a
              runner fleet, keep student data on campus, and extend the emulator and grader without asking anyone.</p>
            <div className="lp-ctas">
              <a className="lp-btn outline" href="https://github.com/ren0777/cloudsandbox">View the repository</a>
              <a className="lp-btn ghost" href="https://github.com/ren0777/cloudsandbox/blob/main/LICENSE">Read the licence</a>
            </div>
          </div>
          <ul className="lp-list">
            <li>One command to build the sandbox images and the stack.</li>
            <li>Six ready-made labs and an instructor Lab Builder.</li>
            <li>Postgres backup/restore, TLS and multi-runner deployment guides.</li>
          </ul>
        </div>
      </section>

      <section className="lp-final">
        <div className="lp-wrap">
          <h2>Ready to launch it?</h2>
          <p className="lp-lede">Start the demo, open a sandbox and get graded in minutes.</p>
          <div className="lp-ctas center">
            <Link href="/login" className="lp-btn primary lg" data-testid="cta-final">Try the demo</Link>
            <Link href="/login?next=/instructor" className="lp-btn outline lg">For instructors</Link>
          </div>
        </div>
      </section>

      <footer className="lp-foot">
        <div className="lp-wrap lp-foot-in">
          <span className="lp-brand small"><span className="lp-dot" aria-hidden />Stackora</span>
          <span className="lp-small">Hands-on cloud labs with real CLI workflows and instant grading.</span>
          <span className="lp-small">Apache-2.0 · © 2026 ren0777</span>
        </div>
      </footer>

      <style>{`
        .lp { --lp-dark: #0b1428; --lp-dark2: #12203d; --lp-cyan: #5fd3f0; background: var(--paper); }
        .lp-wrap { max-width: 1160px; margin: 0 auto; padding: 0 24px; }
        .lp-small { font-size: 13px; color: var(--muted); }
        .lp-eyebrow { font-family: var(--font-mono); font-size: 12px; letter-spacing: .12em; text-transform: uppercase; color: var(--signal-strong); }
        .lp h2 { font-size: clamp(24px, 3vw, 34px); line-height: 1.12; margin: 10px 0 0; }
        .lp-lede { color: var(--muted); font-size: 16px; max-width: 62ch; margin: 12px 0 0; }

        .lp-nav { position: sticky; top: 0; z-index: 40; background: rgba(11, 20, 40, .92); backdrop-filter: blur(10px); border-bottom: 1px solid rgba(255,255,255,.08); }
        .lp-nav-in { display: flex; align-items: center; gap: 20px; height: 62px; }
        .lp-brand { display: inline-flex; align-items: center; gap: 9px; color: #fff; font-family: var(--font-display); font-weight: 700; font-size: 19px; }
        .lp-brand:hover { text-decoration: none; }
        .lp-dot { width: 11px; height: 11px; border-radius: 50%; background: var(--lp-cyan); box-shadow: 0 0 0 4px rgba(95,211,240,.22); }
        .lp-nav nav { display: flex; gap: 2px; margin-left: 8px; }
        .lp-nav nav a { color: #b9c6e2; padding: 8px 12px; border-radius: 8px; font-size: 14px; }
        .lp-nav nav a:hover { color: #fff; background: rgba(255,255,255,.06); text-decoration: none; }
        .lp-nav-cta { margin-left: auto; display: flex; gap: 8px; }
        .lp-btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; border-radius: 10px; padding: 10px 16px; font-weight: 600; font-size: 14px; border: 1px solid transparent; transition: transform .08s ease, background .15s ease; }
        .lp-btn:hover { text-decoration: none; transform: translateY(-1px); }
        .lp-btn.lg { padding: 13px 22px; font-size: 15px; }
        .lp-btn.primary { background: var(--lp-cyan); color: #062033; }
        .lp-btn.primary:hover { background: #7fe0f7; }
        .lp-btn.outline { border-color: rgba(255,255,255,.35); color: #eaf1ff; }
        .lp-btn.outline:hover { background: rgba(255,255,255,.08); }
        .lp-btn.ghost { color: #cfd9ef; border-color: rgba(255,255,255,.18); }
        .lp-btn.ghost:hover { background: rgba(255,255,255,.07); }

        .lp-hero { background: radial-gradient(1100px 500px at 78% -10%, rgba(95,211,240,.20), transparent 60%), linear-gradient(160deg, var(--lp-dark) 0%, var(--lp-dark2) 100%); color: #fff; padding: 84px 0 76px; }
        .lp-hero-in { display: grid; grid-template-columns: 1.05fr .95fr; gap: 48px; align-items: center; }
        .lp-hero-copy h1 { font-size: clamp(46px, 7vw, 76px); line-height: 1; margin: 14px 0 0; letter-spacing: -.03em; }
        .lp-tag { font-family: var(--font-display); font-size: clamp(20px, 2.6vw, 28px); font-weight: 600; margin: 14px 0 0; color: var(--lp-cyan); }
        .lp-sub { font-size: 18px; color: #c7d3ec; margin: 12px 0 0; max-width: 46ch; }
        .lp-ctas { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 26px; }
        .lp-ctas.center { justify-content: center; }
        .lp-note { margin: 18px 0 0; font-size: 13px; color: #93a4c8; }
        .lp-hero-art { position: relative; }
        .lp-term { background: var(--terminal); border: 1px solid #22335a; border-radius: 14px; overflow: hidden; box-shadow: 0 24px 60px rgba(0,0,0,.45); }
        .lp-term-bar { display: flex; align-items: center; gap: 6px; padding: 10px 12px; background: #0a1122; border-bottom: 1px solid #1c2b4a; }
        .lp-term-bar span { width: 10px; height: 10px; border-radius: 50%; background: #2c3d63; }
        .lp-term-bar span:first-child { background: #e0655f; } .lp-term-bar span:nth-child(2) { background: #e0b45f; } .lp-term-bar span:nth-child(3) { background: #58c98a; }
        .lp-term-bar em { margin-left: 10px; font-family: var(--font-mono); font-size: 12px; font-style: normal; color: #8fa2c7; }
        .lp-term pre { margin: 0; padding: 18px; font-family: var(--font-mono); font-size: 13px; line-height: 1.75; color: #b9f0d6; white-space: pre-wrap; }
        .lp-grade { position: absolute; right: -8px; bottom: -26px; display: flex; align-items: center; gap: 12px; background: #fff; color: var(--ink); border-radius: 14px; padding: 12px 16px; box-shadow: 0 16px 40px rgba(3, 10, 26, .35); }
        .lp-grade-ring { display: grid; place-items: center; width: 46px; height: 46px; border-radius: 50%; background: var(--pass-soft); color: var(--pass); font-family: var(--font-display); font-weight: 700; }
        .lp-grade .lp-small { display: block; }

        .lp-strip { background: #fff; border-bottom: 1px solid var(--line); padding: 26px 0; }
        .lp-strip-title { font-family: var(--font-mono); font-size: 12px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); margin: 0 0 14px; }
        .lp-services { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
        .lp-service { border: 1px solid var(--line); border-radius: 12px; padding: 14px; background: linear-gradient(180deg, #fff, #f7f9fd); }
        .lp-svc-name { display: block; font-family: var(--font-display); font-weight: 700; font-size: 18px; color: var(--ink); margin-bottom: 4px; }

        .lp-section { padding: 78px 0; }
        .lp-section.alt { background: #fff; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
        .lp-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 34px; }
        .lp-card { background: #fff; border: 1px solid var(--line); border-radius: 14px; padding: 20px; box-shadow: var(--shadow); }
        .lp-section.alt .lp-card { background: var(--paper); box-shadow: none; }
        .lp-card h3 { margin: 12px 0 6px; font-size: 16px; }
        .lp-card p { margin: 0; color: var(--muted); font-size: 14px; }
        .lp-ic { display: inline-grid; place-items: center; width: 40px; height: 40px; border-radius: 11px; background: var(--signal-soft); color: var(--signal-strong); }

        .lp-workflow { background: var(--ink); color: #fff; padding: 78px 0; }
        .lp-workflow h2 { color: #fff; }
        .lp-workflow .lp-lede { color: #c7d3ec; }
        .lp-workflow .lp-eyebrow { color: var(--lp-cyan); }
        .lp-workflow-in { display: grid; grid-template-columns: 1.05fr .95fr; gap: 48px; align-items: center; }
        .lp-list { margin: 22px 0 0; padding: 0; list-style: none; display: grid; gap: 10px; }
        .lp-list li { padding-left: 26px; position: relative; color: #c7d3ec; font-size: 14.5px; }
        .lp-list li::before { content: "✓"; position: absolute; left: 0; color: var(--lp-cyan); font-weight: 700; }
        .lp-workflow-art pre { margin: 0; background: var(--terminal); border: 1px solid #22335a; border-radius: 14px; padding: 20px; font-family: var(--font-mono); font-size: 13px; line-height: 1.8; color: #b9f0d6; white-space: pre-wrap; }

        .lp-shots { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; margin-top: 34px; }
        .lp-shot { margin: 0; border: 1px solid var(--line); border-radius: 14px; overflow: hidden; background: #fff; box-shadow: var(--shadow); }
        .lp-shot img { display: block; width: 100%; height: auto; }
        .lp-shot figcaption { padding: 12px 14px; font-size: 13px; color: var(--muted); border-top: 1px solid var(--line); }

        .lp-oss { display: grid; grid-template-columns: 1.1fr .9fr; gap: 48px; align-items: center; }
        .lp-oss .lp-list li { color: var(--muted); }
        .lp-oss .lp-list li::before { color: var(--pass); }
        .lp-oss .lp-btn.outline { border-color: var(--line); color: var(--ink); }
        .lp-oss .lp-btn.outline:hover { background: #eef3fa; }
        .lp-oss .lp-btn.ghost { color: var(--muted); border-color: var(--line); }

        .lp-final { background: radial-gradient(900px 380px at 50% -30%, rgba(95,211,240,.22), transparent 65%), linear-gradient(160deg, var(--lp-dark), var(--lp-dark2)); color: #fff; padding: 82px 0; text-align: center; }
        .lp-final h2 { color: #fff; font-size: clamp(28px, 4vw, 42px); }
        .lp-final .lp-lede { color: #c7d3ec; margin: 12px auto 0; }
        .lp-final .lp-btn.outline { border-color: rgba(255,255,255,.35); color: #eaf1ff; }

        .lp-foot { background: #081020; color: #93a4c8; padding: 26px 0; }
        .lp-foot-in { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
        .lp-foot .lp-small { color: #7f90b4; }
        .lp-foot .lp-brand.small { font-size: 15px; margin-right: auto; }

        @media (max-width: 980px) {
          .lp-hero-in, .lp-workflow-in, .lp-oss { grid-template-columns: 1fr; gap: 34px; }
          .lp-services { grid-template-columns: repeat(2, 1fr); }
          .lp-grid { grid-template-columns: repeat(2, 1fr); }
          .lp-nav nav { display: none; }
        }
        @media (max-width: 640px) {
          .lp-services, .lp-grid, .lp-shots { grid-template-columns: 1fr; }
          .lp-grade { position: static; margin-top: 14px; }
        }
      `}</style>
    </div>
  );
}
