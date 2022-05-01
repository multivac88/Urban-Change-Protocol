from pyteal import *

def approval_program():
    # global variables
    creator         = Bytes("creator")    #                         TealType.Bytes
    city            = Bytes("city")       # Txn.application_args[0] TealType.Bytes
    max_threshold   = Bytes("max")        # Txn.application_args[1] TealType.uint64
    min_threshold   = Bytes("min")        # Txn.application_args[2] TealType.uint64
    vault_asset     = Bytes("m_asset")    # Txn.assets[0]           TealType.uint64
    pos_asset       = Bytes("pos_asset")  #                         TealType.uint64
    rwd_asset       = Bytes("rwd_asset")  #                         TealType.uint64
    creation_time   = Bytes("s_date")     #                         TealType.uint64

    # local variables
    deposit_balance   = Bytes("balance") # TealType.uint64
    deposit_timestamp = Bytes("d_timestamp") # TealType.uint64

    # operations
    op_contract_opt_in_vault_asset = Bytes("contract_opt_in_vault_asset") # handled in optin
    op_usr_opt_in                  = Bytes("usr_opt_in")                  # handled in optin
    op_usr_deposit                 = Bytes("usr_deposit")                 # handled in noop
    op_usr_withdrawal              = Bytes("usr_withdrawal")              # handled in noop

    # Summary: opts contract into an asset
    # fees paid with caller tx fees (2 * min_fee)
    # global balance is 0 maintained by contract and accessed with AssetHolding class functions
    # can be used to opt contract in multiple assets as long as a global var is declared in the contract for asset
    # @requirements:
    # - assets[0] exists and is equivalent to vault_asset 
    # preconditions:
    # - Txn.type_enum() == TxnType.ApplicationCall
    # - param: asset_id = App.globalGet(asset_global_var) is already set 
    # - contract is not already opted into this asset
    # - sender is the creator of the contract
    # - tx is not part of a group
    # - fees of tx is equal to twice min fee to cover caller cost and inner transaction fee
    # - rekey set to zero address
    # postconditions:
    # - contract opted into specified asset 
    @Subroutine(TealType.none)
    def contract_opt_in_asset(asset_id: Expr):
        asset_opt_in_check = AssetHolding.balance(Global.current_application_address(), Int(0)) # requires index into asset array (Int(0))
        return Seq(
            asset_opt_in_check,
            Assert(
                And(
                    # sanity checks
                    Txn.type_enum() == TxnType.ApplicationCall,
                    Global.group_size() == Int(1),
                    Txn.group_index() == Int(0),
                    Txn.rekey_to() == Global.zero_address(),

                    # logic checks
                    Txn.assets.length() == Int(1), # make sure assets array is length one assets[0] should be asset_id
                    Txn.assets[0] == asset_id, # check asset in array at index 0 is indeed equal to the subroutines asset_id
                    asset_opt_in_check.hasValue() == Int(0), # finally check if contracts balance of asset is 0 -> not opted into asset
                    Txn.sender() == App.globalGet(creator),
                    Txn.fee() >= Global.min_txn_fee() * Int(2),
                )
            ),
            # have contract opt-in to vault asset (Txn.assets[0]) via inner tx
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.asset_receiver: Global.current_application_address(),
                TxnField.asset_amount: Int(0), # opt-in tx sends 0 of asset to itself
                TxnField.fee: Int(0), # zero fee takes caller tx fee to pay for inner tx
                TxnField.xfer_asset: asset_id, 
            }),
            InnerTxnBuilder.Submit(),
            Approve()
        )

    # summary: opt user into contract, 
    # check if user is not already opted in and has sufficent fee to pay caller tx fees
    # preconditions:
    # - standard sanity checks
    # postcondition
    # - user opted in
    # - user deposit balance and timestamp set to 0, later deposits will set timestamp
    @Subroutine(TealType.none)
    def usr_opt_in():
        return Seq(
            Assert(
                And(
                    # sanity checks
                    Txn.type_enum() == TxnType.ApplicationCall,
                    Global.group_size() == Int(1),
                    Txn.group_index() == Int(0),
                    Txn.rekey_to() == Global.zero_address(),
                    
                    # logic checks
                    App.optedIn(Txn.sender(), Global.current_application_id()) == Int(0),
                    Txn.fee() >= Global.min_txn_fee(),
                )
            ),
            App.localPut(Txn.sender(), deposit_balance, Int(0)),
            App.localPut(Txn.sender(), deposit_timestamp, Int(0)),
            Approve()
        )
    # NOTE can check whether contracts balance exceeds min_threshold and branch from here
    # NOTE if tx fails anywhere during execution everthing reverts to pre call state.
    # summary: user sends asset transfer to contract, a users local vars are updates,
    # deposit_balance is incremented 
    # users deposit timestamp is set to current
    # preconditions:
    # - sanity checks and asset_close_to == Global.zero_address
    # - user is opted in contract
    # - txn type is asset transfer
    # - asset receiver is contract address
    # - asset ID being sent is the vault_asset declared in global state (vault_asset)
    # - asset amount greator than 0
    # - fee covers tx cost
    # postconditions:
    # - a user's deposit amount is incremented by asset sent amount
    # - a user's deposit timestamp is set to current timestamp 
    @Subroutine(TealType.none)
    def usr_deposit():
        return Seq(
            Assert(
                And(

                    # sanity checks
                    Txn.type_enum() == TxnType.AssetTransfer,
                    Global.group_size() == Int(1),
                    Txn.group_index() == Int(0),
                    Txn.rekey_to() == Global.zero_address(),
                    Txn.asset_close_to() == Global.zero_address(), 

                    # logic checks
                    # is txn.sender() == txn.asset_sender()??
                    # check if user is opted into asset being sent??
                    App.optedIn(Txn.sender(), Global.current_application_id()),
                    Txn.asset_receiver() == Global.current_application_address(),
                    Txn.xfer_asset() == App.globalGet(vault_asset),
                    Txn.asset_amount() > Int(0),
                    Txn.fee() >= Global.min_txn_fee(),
                )
            ),
            # increment senders vault_asset by asset_amount
            App.localPut(Txn.sender(), deposit_balance, App.localGet(Txn.sender(), deposit_balance) + Txn.asset_amount()),
            # recent deposit overwrites timestamp #change
            App.localPut(Txn.sender(), deposit_timestamp, Global.latest_timestamp()),
            Approve(),
        )

    # summary:
    # Txn.application_args[0] = Bytes("usr_withdrawal") 
    # Txn.application_args[1] = amount
    # Txn.assets[0] = vault_asset
    # deduct withdrawal amount from users local deposit amount
    # asset transfer requested amount to user, use pooling fees (caller pays for call and inner tx)
    # preconditions:
    # - sanity checks
    # - applications args contain the withdrawal operation ([0]) and withdrawal amount ([1])
    # - TXn.assets[0] is the asset user wants to withdrawal, in this case we assert it is the vault asset
    # - user is opted in 
    # - withdrawal amount is > 0 and <= deposit_balance
    # - fees in caller tx is twice that of the global min tx fee. pays for caller and inner tx via fee pooling
    # postconditions:
    # - users deposit_amount is reduced by specified amount
    # - contracts vault_asset balance is reduced by the specified amount
    # - user's deposit timestamp is invariant
    @Subroutine(TealType.none)
    def usr_withdrawal():
        temp = ScratchVar(TealType.uint64)
        return Seq(
            Assert(
                And(
                    # sanity checks
                    Txn.type_enum() == TxnType.ApplicationCall,
                    Global.group_size() == Int(1),
                    Txn.group_index() == Int(0),
                    Txn.rekey_to() == Global.zero_address(),

                    # logic checks
                    Txn.application_args.length() == Int(2),
                    Txn.assets.length() == Int(1),
                    App.optedIn(Txn.sender(), Global.current_application_id()),
                    Txn.assets[0] == App.globalGet(vault_asset),
                    Btoi(Txn.application_args[1]) > Int(0), 
                    Btoi(Txn.application_args[1]) <= App.localGet(Txn.sender(), deposit_balance), 
                    Txn.fee() >= Global.min_txn_fee() * Int(2),
                )
            ),
            # deduct user deposit_balance by amount specified in Txn.appllication_args[1]
            temp.store(App.localGet(Txn.sender(), deposit_balance)),
            App.localPut(Txn.sender(), deposit_balance, temp.load() - Btoi(Txn.application_args[1])),
            # create and transfer asset via inner txn
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields({
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.asset_receiver: Txn.sender(),
                TxnField.asset_amount: Btoi(Txn.application_args[1]),
                TxnField.fee: Int(0), # zero fee takes caller tx fee to pay for inner tx (fee pooling)
                TxnField.xfer_asset: Txn.assets[0], 
            }),
            InnerTxnBuilder.Submit(),
            Approve(),
        )

    # preconditions:
    # - txn creates contract -> checked via Txn.application_id() == Int(0)
    # - 3 application_args 
    # - 1 asset ID
    # postconditions:
    # - glabal vars: creator, city, max/min thresholds, vault asset ID and creation timestamp initialized
    handle_creation = Seq(
        Assert(
            And(
                Txn.application_args.length() == Int(3),
                Txn.assets.length() == Int(1),
            )
        ),
        App.globalPut(creator, Txn.sender()),
        App.globalPut(city, Txn.application_args[0]),
        App.globalPut(max_threshold, Btoi(Txn.application_args[1])),
        App.globalPut(min_threshold, Btoi(Txn.application_args[2])),
        App.globalPut(vault_asset, Txn.assets[0]),
        App.globalPut(creation_time, Global.latest_timestamp()),
        Approve(),
    )

    handle_optin = Seq(
        Cond(
            [Txn.application_args[0] == op_contract_opt_in_vault_asset, contract_opt_in_asset(App.globalGet(vault_asset))],
            # other contract asset optins go here
            [Txn.application_args[0] == op_usr_opt_in, usr_opt_in()]
        ), 
        Reject(),
    )

    handle_noop = Seq(
        Cond(
            [Txn.application_args[0] == op_usr_deposit, usr_deposit()],
            [Txn.application_args[0] == op_usr_withdrawal, usr_withdrawal()]
        ),
        Reject()
    )

    handle_updateapp = Err()

    handle_deleteapp = Err()

    handle_closeout = Err()

    program = Cond(
        [Txn.application_id() == Int(0), handle_creation],
        [Txn.on_completion() == OnComplete.OptIn, handle_optin],
        [Txn.on_completion() == OnComplete.CloseOut, handle_closeout],
        [Txn.on_completion() == OnComplete.UpdateApplication, handle_updateapp],
        [Txn.on_completion() == OnComplete.DeleteApplication, handle_deleteapp],
        [Txn.on_completion() == OnComplete.NoOp, handle_noop],
    )
    # Mode.Application specifies that this is a smart contract
    return compileTeal(program, Mode.Application, version=5)

def clear_state_program():
    program = Return(Int(1))
    # Mode.Application specifies that this is a smart contract
    return compileTeal(program, Mode.Application, version=5)
