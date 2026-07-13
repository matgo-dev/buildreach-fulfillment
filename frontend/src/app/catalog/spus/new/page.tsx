"use client";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SpuForm } from "@/components/catalog/SpuForm";

function NewSpuInner() {
  const router = useRouter();
  const sp = useSearchParams();
  const back = () => router.push("/catalog/spus");
  const category = sp.get("category") || undefined; // 列表左树选中的分类(叶子直接预填,父节点仅预展开引导下钻)
  const isLeaf = sp.get("leaf") === "1";
  return (
    <SpuForm
      open
      spu={undefined}
      defaultCategoryCode={category}
      defaultCategoryIsLeaf={isLeaf}
      onClose={back}
      onSaved={back}
    />
  );
}

export default function NewSpuPage() {
  // useSearchParams 需 Suspense 边界(Next app router)。
  return (
    <Suspense fallback={null}>
      <NewSpuInner />
    </Suspense>
  );
}
