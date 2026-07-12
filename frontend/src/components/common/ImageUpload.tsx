"use client";
import { useState } from "react";
import { Upload, App } from "antd";
import { PlusOutlined, LoadingOutlined, DeleteOutlined } from "@ant-design/icons";
import { uploadImage } from "@/lib/upload";
import { imageUrl } from "@/lib/image";

const ACCEPT = ["image/jpeg", "image/png", "image/webp", "image/gif"];
const MAX_BYTES = 5 * 1024 * 1024;

/**
 * 商品图上传(DESIGN §8):存 object key(非 URL),选图即两步直传。
 * 受控:`value` 为 key,`onChange(key|null)` 回写表单。需 product:manage(后端守)。
 */
export function ImageUpload({
  value,
  onChange,
  disabled,
  width = 200,
}: {
  value?: string | null;
  onChange?: (key: string | null) => void;
  disabled?: boolean;
  /** 预览请求宽度(OSS 实时缩略) */
  width?: number;
}) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);

  async function handle(file: File): Promise<boolean> {
    if (!ACCEPT.includes(file.type)) {
      message.error("仅支持 jpeg/png/webp/gif 图片");
      return false;
    }
    if (file.size > MAX_BYTES) {
      message.error("图片需小于 5MB");
      return false;
    }
    setLoading(true);
    try {
      const key = await uploadImage(file);
      onChange?.(key);
      message.success("图片已上传");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "上传失败");
    } finally {
      setLoading(false);
    }
    return false; // 阻断 AntD 默认上传行为
  }

  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
      <Upload
        listType="picture-card"
        showUploadList={false}
        accept={ACCEPT.join(",")}
        disabled={disabled || loading}
        beforeUpload={(f) => handle(f as File)}
      >
        {value ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imageUrl(value, width)}
            alt="商品图"
            style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 6 }}
          />
        ) : (
          <div>
            {loading ? <LoadingOutlined /> : <PlusOutlined />}
            <div style={{ marginTop: 8 }}>上传</div>
          </div>
        )}
      </Upload>
      {value && !disabled && (
        <a onClick={() => onChange?.(null)} style={{ color: "#991b1b", fontSize: 12 }}>
          <DeleteOutlined /> 移除
        </a>
      )}
    </div>
  );
}
