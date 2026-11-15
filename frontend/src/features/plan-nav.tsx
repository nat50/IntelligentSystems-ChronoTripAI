import Link from "next/link";
import type { NavItem } from "@/components/ui";
import type { TripState } from "@/lib/trip-store";
import s from "./screen.module.css";

type Step = "/plan" | "/plan/places" | "/plan/itinerary";

/** Figma planner steps: "1 Trip setup · 2 Pick places · 3 Itinerary", finished steps get a ✓ */
export function planNav(state: TripState, active: Step): NavItem[] {
  const at = ["/plan", "/plan/places", "/plan/itinerary"].indexOf(active);
  const hasPlan = Boolean(state.itinerary);
  return [
    { href: "/plan", label: "Trip setup", step: "1", done: at > 0 || state.selected.length > 0 },
    { href: "/plan/places", label: "Pick places", step: "2", done: at > 1 || hasPlan },
    { href: "/plan/itinerary", label: "Itinerary", step: "3", disabled: !hasPlan && at < 2 },
  ];
}

/** "Ho Chi Minh City · 3 days  Edit" (T2, T3 top bar) */
export function TripSummary({ state }: { state: TripState }) {
  return (
    <span className={s.tripSummary}>
      <span>
        {state.city} · {state.days} {state.days === 1 ? "day" : "days"}
      </span>
      <Link href="/plan" className={s.editLink}>
        Edit
      </Link>
    </span>
  );
}
