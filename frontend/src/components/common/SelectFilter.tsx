"use client";
import { DownOutlined } from "@ant-design/icons";
import { ConfigProvider, Menu } from "antd";
import type { ColumnType } from "antd/es/table";
import { colors } from "@/lib/tokens";

/**
 * 列头「单选枚举」筛选器 —— 平台唯一承载点(DESIGN §7 次要枚举列)。
 *
 * 为什么不用 AntD 内置 `filters` + `filterMultiple:false`:内置面板是「单选钮 + 重置/确定」两段式,
 * 选一个值要点 3 次(开→勾→确定)。次要枚举列的语义就是一个下拉单选,应当**即选即生效**(点 2 次:开→选),
 * 与工具条上的 Select 行为一致。漏斗图标同样误导 —— 它暗示多条件筛选面板,这里只是个下拉,故换成下拉尖头。
 *
 * 用法:展开进列定义,options 沿用 AntD `ColumnFilterItem` 形状({ text, value })。
 *   { title: "币种", dataIndex: "currency",
 *     ...selectFilter(CURRENCIES.map((c) => ({ text: c, value: c }))),
 *     filteredValue: currency ? [currency] : null }   // 服务端过滤时受控;客户端过滤则改配 onFilter
 *
 * 选中态由 AntD 传入的 `selectedKeys` 反映(受控列来自 `filteredValue`,非受控列来自内部态),
 * 故本工具不需要外部再喂一遍当前值。
 */

export interface SelectFilterOption {
  text: string;
  value: string;
}

/** 「全部」项的哨兵 key —— 选中它 = 清空该列筛选(等价内置面板的「重置」)。业务枚举一律英文 code,不会撞。 */
const ALL_KEY = "__ALL__";

export function selectFilter<RecordType>(
  options: SelectFilterOption[],
): Pick<ColumnType<RecordType>, "filterIcon" | "filterDropdown"> {
  return {
    filterIcon: (filtered: boolean) => (
      <DownOutlined style={{ fontSize: 10, color: filtered ? colors.brand : undefined }} />
    ),
    filterDropdown: ({ selectedKeys, setSelectedKeys, confirm }) => (
      // 项高对齐 AntD 控件高(controlHeight=32)—— 让它读起来就是个 Select 下拉,而非 Menu 导航。
      <ConfigProvider theme={{ components: { Menu: { itemHeight: 32, itemMarginBlock: 2 } } }}>
        <Menu
          selectable
          selectedKeys={[(selectedKeys[0] as string | undefined) ?? ALL_KEY]}
          style={{ borderInlineEnd: "none", minWidth: 120 }}
          items={[
            { key: ALL_KEY, label: "全部" },
            ...options.map((o) => ({ key: o.value, label: o.text })),
          ]}
          onClick={({ key }) => {
            // setSelectedKeys 走 AntD 的同步态(useSyncState),故紧随其后的 confirm 读到的就是新值。
            setSelectedKeys(key === ALL_KEY ? [] : [key]);
            confirm({ closeDropdown: true });
          }}
        />
      </ConfigProvider>
    ),
  };
}
