import InstallEntry from "@/src/components/InstallEntry";

export default function EmployeeEntry() {
  return (
    <InstallEntry
      kind="employee"
      title="Employee App"
      subtitle="Sign in with your Employee Code / phone and PIN to punch attendance, view payslips and apply for leave."
      loginPath="/pin-login"
      manifestHref="/manifest-employee.json"
      accentIcon="person"
    />
  );
}
