import { initials } from "@/lib/team";

export function Avatar({ name }: { name: string }) {
  return <span aria-hidden className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-sm font-semibold text-accent">{initials(name)}</span>;
}
