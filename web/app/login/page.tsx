import { Logo } from "@/components/Logo";

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex justify-center"><Logo size={28} /></div>
        <div className="card p-7">
          <h1 className="text-lg font-semibold tracking-tight">Sign in to Flux</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Use your GitHub account. We only read your public profile.
          </p>

          {/* Native form POST avoids client-side fetch — browser follows the
              302 to GitHub, which then redirects back to /auth/github/callback */}
          <a href="/auth/github/login" className="btn-primary mt-6 w-full">
            <GitHubMark /> Continue with GitHub
          </a>

          <div className="mt-6 text-center text-xs text-zinc-500">
            By signing in you agree to BYOK — bring your own LLM API key.
          </div>
        </div>
      </div>
    </div>
  );
}

function GitHubMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M12 .5C5.65.5.5 5.66.5 12.02c0 5.1 3.29 9.41 7.86 10.94.57.1.79-.25.79-.55 0-.27-.01-1.16-.02-2.1-3.2.7-3.87-1.36-3.87-1.36-.52-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.2 1.77 1.2 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.55-.29-5.23-1.28-5.23-5.7 0-1.26.45-2.29 1.19-3.1-.12-.3-.52-1.48.11-3.08 0 0 .97-.31 3.19 1.18a11.06 11.06 0 0 1 2.9-.39c.98 0 1.98.13 2.9.39 2.22-1.49 3.19-1.18 3.19-1.18.63 1.6.24 2.78.12 3.08.74.81 1.18 1.84 1.18 3.1 0 4.44-2.69 5.41-5.25 5.69.41.36.78 1.05.78 2.12 0 1.53-.01 2.76-.01 3.13 0 .3.21.66.8.55A11.51 11.51 0 0 0 23.5 12C23.5 5.66 18.34.5 12 .5Z" />
    </svg>
  );
}
