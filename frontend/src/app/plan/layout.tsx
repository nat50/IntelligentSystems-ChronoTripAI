import type { Metadata } from "next";
import { TripProvider } from "@/lib/trip-store";

export const metadata: Metadata = { title: "Plan your trip · ChronoTrip" };

export default function PlanLayout({ children }: LayoutProps<"/plan">) {
  return <TripProvider>{children}</TripProvider>;
}
