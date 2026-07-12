"use client";
import { useRouter } from "next/navigation";
import { SpuForm } from "@/components/catalog/SpuForm";

export default function NewSpuPage() {
  const router = useRouter();
  const back = () => router.push("/catalog/spus");
  return <SpuForm open spu={undefined} onClose={back} onSaved={back} />;
}
