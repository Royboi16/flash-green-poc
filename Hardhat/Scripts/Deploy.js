async function main() {
  const [deployer] = await ethers.getSigners();

  // 1) Deploy lender with 5bps fee
  const FlashLoan = await ethers.getContractFactory("FlashLoan");
  const lender = await FlashLoan.deploy(5);
  await lender.deployed();

  // 2) Seed with 100 ETH
  await deployer.sendTransaction({
    to: lender.address,
    value: ethers.utils.parseEther("100")
  });

  console.log("FlashLoan deployed at:", lender.address);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
