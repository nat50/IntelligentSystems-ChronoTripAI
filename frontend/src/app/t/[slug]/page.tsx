import type { Metadata } from "next";
import { Suspense } from "react";
import { SharedScreen } from "@/features/trips/SharedScreen";

export const metadata: Metadata = { title: "Shared trip · ChronoTrip" };

// the slug is only known at request time, so it is read inside Suspense (Cache Components)
export default function SharedTripPage({ params }: PageProps<"/t/[slug]">) {
  return <Suspense fallback={null}>{params.then(({ slug }) => <SharedScreen slug={slug} />)}</Suspense>;
}
