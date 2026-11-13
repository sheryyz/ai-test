import { useState, type FormEvent } from "react";
import { BrandMark, Icon, type IconName } from "../components/icons";
import { api, type AuthState, type AuthUser } from "../lib/api";

const POINTS: { icon: IconName; title: string; text: string }[] = [
  { icon: "chat", title: "像真实用户一样对话", text: "中途改主意、撤回同意、在工具返回里藏指令，多轮试探你的 Agent" },
  { icon: "shield", title: "每一步都核对授权", text: "Agent 每调用一次敏感操作，都对照用户此刻真正同意了什么" },
  { icon: "database", title: "以数据库的真实变化为准", text: "不只听 Agent 怎么说，还核对它实际改了什么；修好后一键复测" },
];

export function Login({ auth, onSignedIn }: { auth: AuthState; onSignedIn: (u: AuthUser) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn(u: string, p: string) {
    setBusy(true);
    setError(null);
    try {
      const res = await api.login(u, p);
      onSignedIn(res.user);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!username || !password) {
      setError("请输入用户名和密码");
      return;
    }
    void signIn(username, password);
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]" style={{ background: "var(--page)" }}>
      <aside className="relative hidden overflow-hidden px-12 py-12 text-white lg:flex lg:flex-col" style={{ background: "linear-gradient(150deg, #1e40af 0%, #312e81 58%, #1e1b4b 100%)" }}>
        <Backdrop />
        <div className="relative flex items-center gap-3">
          <BrandMark size={38} />
          <div>
            <div className="text-lg font-semibold tracking-tight">ConsentTrace</div>
            <div className="text-xs text-white/65">AI Agent 授权安全测试平台</div>
          </div>
        </div>
        <div className="relative mt-auto max-w-lg">
          <h1 className="text-[34px] font-semibold leading-tight tracking-tight">
            你的 AI Agent，
            <br />
            会不会在用户没同意时就动手？
          </h1>
          <p className="mt-4 text-[15px] leading-relaxed text-white/75">ConsentTrace 自动和你的 Agent 进行多轮对话，找出它“没等用户确认就执行”的那一步，并告诉你数据库里到底被改了什么。</p>
          <ul className="mt-8 space-y-4">
            {POINTS.map((p) => (
              <li key={p.title} className="flex gap-3.5">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg" style={{ background: "rgba(255,255,255,.12)" }}>
                  <Icon name={p.icon} size={18} />
                </span>
                <span>
                  <span className="block text-sm font-semibold">{p.title}</span>
                  <span className="block text-[13px] leading-relaxed text-white/65">{p.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div className="relative mt-auto pt-10 text-[11px] text-white/45">被测 Agent 以独立进程运行，平台不修改它的代码；每个结论都能追溯到对话记录和数据库变化。</div>
      </aside>

      <main className="flex items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-[400px]">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <BrandMark size={36} />
            <div>
              <div className="text-lg font-semibold text-ink">ConsentTrace</div>
              <div className="text-xs text-muted">AI Agent 授权安全测试平台</div>
            </div>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight text-ink">登录</h2>
          <p className="mt-1.5 text-sm text-ink-2">登录后即可接入你的 Agent、发起测试、查看报告。</p>

          <form onSubmit={submit} className="mt-7 space-y-4" noValidate>
            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-ink-2">用户名</span>
              <span className="relative block">
                <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">
                  <Icon name="user" size={16} />
                </span>
                <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} className="field w-full pl-9" placeholder="输入用户名" />
              </span>
            </label>
            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-ink-2">密码</span>
              <span className="relative block">
                <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">
                  <Icon name="lock" size={16} />
                </span>
                <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className="field w-full pl-9" placeholder="输入密码" />
              </span>
            </label>
            {error && (
              <p role="alert" className="rounded-lg px-3 py-2 text-xs" style={{ background: "var(--critical-wash)", color: "var(--ink)" }}>
                {error}
              </p>
            )}
            <button type="submit" disabled={busy} className="btn btn-primary btn-lg w-full">
              {busy ? "正在登录…" : "登录"}
            </button>
          </form>

          {auth.demo && (
            <>
              <div className="my-6 flex items-center gap-3 text-[11px] text-muted">
                <span className="h-px flex-1" style={{ background: "var(--border)" }} />
                还没有账号
                <span className="h-px flex-1" style={{ background: "var(--border)" }} />
              </div>
              <button type="button" disabled={busy} onClick={() => void signIn(auth.demo!.username, auth.demo!.password)} className="btn btn-secondary btn-lg w-full">
                <Icon name="play" size={16} />
                使用演示账号一键进入
              </button>
              <p className="mt-2.5 text-center text-[11px] text-muted">
                演示账号 <span className="mono text-ink-2">{auth.demo.username}</span> / <span className="mono text-ink-2">{auth.demo.password}</span>，可体验全部功能
              </p>
            </>
          )}
          <p className="mt-10 text-center text-[11px] text-muted">管理员可用 <span className="mono">consenttrace user add &lt;用户名&gt;</span> 添加账号</p>
        </div>
      </main>
    </div>
  );
}

/** A faint trace drawing behind the brand panel: lanes, steps, one flagged step. Decorative only. */
function Backdrop() {
  return (
    <svg className="pointer-events-none absolute inset-0 size-full" viewBox="0 0 600 800" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <g stroke="white" strokeOpacity={0.07} strokeWidth={1}>
        {[160, 230, 300, 370].map((y) => (
          <line key={y} x1={0} x2={600} y1={y} y2={y} />
        ))}
      </g>
      <g fill="white" fillOpacity={0.16}>
        {[60, 140, 220, 300, 380, 460, 540].map((x, i) => (
          <circle key={x} cx={x} cy={[160, 230, 230, 300, 230, 370, 230][i]} r={5} />
        ))}
      </g>
      <path d="M60 160 140 230 220 230 300 300 380 230 460 370 540 230" stroke="white" strokeOpacity={0.12} strokeWidth={1.5} fill="none" />
      <rect x={452} y={362} width={16} height={16} transform="rotate(45 460 370)" fill="#f87171" fillOpacity={0.55} />
    </svg>
  );
}
