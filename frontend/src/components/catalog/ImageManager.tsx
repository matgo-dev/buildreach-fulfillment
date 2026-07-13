"use client";
import { useState } from "react";
import { Upload, App, Typography } from "antd";
import { PlusOutlined, LoadingOutlined, StarFilled, StarOutlined, CloseOutlined } from "@ant-design/icons";
import { uploadImage } from "@/lib/upload";
import { imageUrl } from "@/lib/image";
import { ImageRefIn } from "@/lib/catalog";

const { Text } = Typography;
const ACCEPT = ["image/jpeg", "image/png", "image/webp", "image/gif"];
const MAX_BYTES = 20 * 1024 * 1024; // 与后端硬限一致

/** 单区图块网格:拖拽排序 + 删除 + 可选封面星 + 上传(达上限隐藏)。 */
export function ImageZone({
  title,
  hint,
  keys,
  onChange,
  max,
  coverKey,
  onSetCover,
}: {
  title: string;
  hint?: string;
  keys: string[];
  onChange: (keys: string[]) => void;
  max: number;
  coverKey?: string;
  onSetCover?: (key: string) => void;
}) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [dragIdx, setDragIdx] = useState<number | null>(null);

  async function handleUpload(file: File): Promise<boolean> {
    if (!ACCEPT.includes(file.type)) {
      message.error("仅支持 jpeg/png/webp/gif 图片");
      return false;
    }
    if (file.size > MAX_BYTES) {
      message.error("单图不超过 20MB");
      return false;
    }
    setLoading(true);
    try {
      const key = await uploadImage(file);
      onChange([...keys, key]);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "上传失败");
    } finally {
      setLoading(false);
    }
    return false; // 阻断 AntD 默认上传
  }

  function reorder(from: number, to: number) {
    if (from === to) return;
    const next = [...keys];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    onChange(next);
  }

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <span style={{ fontWeight: 600, color: "#102441" }}>
          {title} <Text type="secondary">({keys.length}{max ? ` · ${keys.length}/${max}` : ""})</Text>
        </span>
      </div>
      {hint && <div style={{ margin: "2px 0 8px", fontSize: 12, color: "#6b7a90" }}>{hint}</div>}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {keys.map((key, i) => {
          const isCover = onSetCover && key === coverKey;
          return (
            <div
              key={key}
              className="group"
              draggable
              onDragStart={() => setDragIdx(i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (dragIdx !== null) reorder(dragIdx, i);
                setDragIdx(null);
              }}
              style={{
                position: "relative",
                width: 96,
                height: 96,
                borderRadius: 8,
                overflow: "hidden",
                border: isCover ? "2px solid #003366" : "1px solid #dbe4ea",
                cursor: "grab",
                flex: "none",
              }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={imageUrl(key, 200)}
                alt=""
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
              {isCover && (
                <span
                  style={{
                    position: "absolute", top: 0, left: 0, background: "#003366", color: "#fff",
                    fontSize: 11, padding: "1px 6px", borderBottomRightRadius: 6,
                  }}
                >
                  主图
                </span>
              )}
              <div
                className="opacity-0 transition-opacity duration-150 group-hover:opacity-100"
                style={{
                  position: "absolute", inset: 0, display: "flex", alignItems: "center",
                  justifyContent: "center", gap: 12, background: "rgba(0,0,0,0.35)",
                }}
              >
                {onSetCover && !isCover && (
                  <StarOutlined
                    title="设为主图"
                    style={{ color: "#fff", fontSize: 18, cursor: "pointer" }}
                    onClick={() => onSetCover(key)}
                  />
                )}
                {isCover && <StarFilled style={{ color: "#FF6B35", fontSize: 18 }} />}
                <CloseOutlined
                  title="移除"
                  style={{ color: "#fff", fontSize: 18, cursor: "pointer" }}
                  onClick={() => onChange(keys.filter((k) => k !== key))}
                />
              </div>
            </div>
          );
        })}
        {keys.length < max && (
          <Upload
            listType="picture-card"
            showUploadList={false}
            accept={ACCEPT.join(",")}
            disabled={loading}
            beforeUpload={(f) => handleUpload(f as File)}
          >
            <div>
              {loading ? <LoadingOutlined /> : <PlusOutlined />}
              <div style={{ marginTop: 6, fontSize: 12 }}>上传图片</div>
            </div>
          </Upload>
        )}
      </div>
    </div>
  );
}

// ---- SPU 图片管理器:主图/轮播(封面可切)+ 详情图两区 ----

const MAIN_MAX = 6;
const DETAIL_MAX = 12;

function splitRefs(refs: ImageRefIn[]) {
  const mainGallery = refs
    .filter((r) => r.image_type === "MAIN" || r.image_type === "GALLERY")
    .sort((a, b) => a.sort_order - b.sort_order);
  const detail = refs
    .filter((r) => r.image_type === "DETAIL")
    .sort((a, b) => a.sort_order - b.sort_order);
  const cover = refs.find((r) => r.image_type === "MAIN")?.image_key;
  return {
    mainKeys: mainGallery.map((r) => r.image_key),
    detailKeys: detail.map((r) => r.image_key),
    cover,
  };
}

function buildRefs(mainKeys: string[], coverKey: string | undefined, detailKeys: string[]): ImageRefIn[] {
  const cover = mainKeys.length && (!coverKey || !mainKeys.includes(coverKey)) ? mainKeys[0] : coverKey;
  const main: ImageRefIn[] = mainKeys.map((k, i) => ({
    image_key: k,
    image_type: k === cover ? "MAIN" : "GALLERY",
    sort_order: i,
  }));
  const detail: ImageRefIn[] = detailKeys.map((k, i) => ({
    image_key: k,
    image_type: "DETAIL",
    sort_order: i,
  }));
  return [...main, ...detail];
}

export function SpuImageManager({
  value,
  onChange,
}: {
  value: ImageRefIn[];
  onChange: (refs: ImageRefIn[]) => void;
}) {
  const { mainKeys, detailKeys, cover } = splitRefs(value);
  return (
    <>
      <ImageZone
        title="商品主图 / 轮播图"
        hint="展示在商品顶部轮播区,第一张(★)为封面主图;可拖拽排序、☆ 切换封面"
        keys={mainKeys}
        max={MAIN_MAX}
        coverKey={cover}
        onSetCover={(k) => onChange(buildRefs(mainKeys, k, detailKeys))}
        onChange={(next) => onChange(buildRefs(next, cover, detailKeys))}
      />
      <ImageZone
        title="详情页图"
        hint="展示在商品详情描述区的长图;可拖拽排序"
        keys={detailKeys}
        max={DETAIL_MAX}
        onChange={(next) => onChange(buildRefs(mainKeys, cover, next))}
      />
    </>
  );
}
